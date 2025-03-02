# Copyright 2019 DeepMind Technologies Ltd. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Computes a Best-Response policy.

The goal if this file is to be the main entry-point for BR APIs in Python.

TODO(author2): Also include computation using the more efficient C++
`TabularBestResponse` implementation.
"""

import collections
import random

from open_spiel.python import policy as openspiel_policy
from open_spiel.python.algorithms import get_all_states
from open_spiel.python.algorithms import noisy_policy
from open_spiel.python.algorithms import policy_utils
import pyspiel

eps = 0.000000001

def _memoize_method(method):
  """Memoize a single-arg instance method using an on-object cache."""
  cache_name = "cache_" + method.__name__

  def wrap(self, arg):
    key = str(arg)
    try:
      # temporary hack/fix to make BRs work with games whose `str()` has imperfect recall (and/or is otherwise not a perfect representation of state)
      # probably can revert back once the alternate BR mentioned in https://github.com/deepmind/open_spiel/issues/565#issuecomment-828570794 is in.
      key = arg.history_str()
    except Exception as e:
      pass
    cache = vars(self).setdefault(cache_name, {})
    if key not in cache:
      cache[key] = method(self, arg)
    return cache[key]

  return wrap


def compute_states_and_info_states_if_none(game,
                                           all_states=None,
                                           state_to_information_state=None):
  """Returns all_states and/or state_to_information_state for the game.

  To recompute everything, pass in None for both all_states and
  state_to_information_state. Otherwise, this function will use the passed in
  values to reconstruct either of them.

  Args:
    game: The open_spiel game.
    all_states: The result of calling get_all_states.get_all_states. Cached for
      improved performance.
    state_to_information_state: A dict mapping str(state) to
      state.information_state for every state in the game. Cached for improved
      performance.
  """
  if all_states is None:
    all_states = get_all_states.get_all_states(
        game,
        depth_limit=-1,
        include_terminals=False,
        include_chance_states=False)

  if state_to_information_state is None:
    state_to_information_state = {
        state: all_states[state].information_state_string()
        for state in all_states
    }

  return all_states, state_to_information_state


class BestResponsePolicy(openspiel_policy.Policy):
  """Computes the best response to a specified strategy."""

  def __init__(self, game, player_id, policy, root_state=None,
               cut_threshold=0.0, add_noise=False):
    """Initializes the best-response calculation.

    Args:
      game: The game to analyze.
      player_id: The player id of the best-responder.
      policy: A `policy.Policy` object.
      root_state: The state of the game at which to start analysis. If `None`,
        the game root state is used.
      cut_threshold: The probability to cut when calculating the value.
        Increasing this value will trade off accuracy for speed.
    """
    self._num_players = game.num_players()
    self._player_id = player_id
    self._policy = policy
    if root_state is None:
      root_state = game.new_initial_state()
    self._root_state = root_state
    self.infosets = self.info_sets(root_state)
    self._add_noise = add_noise
    self.expanded_infostates = 0
    self._cut_threshold = cut_threshold

  def info_sets(self, state):
    """Returns a dict of infostatekey to list of (state, cf_probability)."""
    infosets = collections.defaultdict(list)
    for s, p in self.decision_nodes(state):
      infosets[s.information_state_string(self._player_id)].append((s, p))
    return dict(infosets)

  def decision_nodes(self, parent_state):
    """Yields a (state, cf_prob) pair for each descendant decision node."""
    if not parent_state.is_terminal():
      if parent_state.current_player() == self._player_id:
        yield (parent_state, 1.0)
      for action, p_action in self.transitions(parent_state):
        for state, p_state in self.decision_nodes(parent_state.child(action)):
          yield (state, p_state * p_action)

  def transitions(self, state):
    """Returns a list of (action, cf_prob) pairs from the specified state."""
    if state.current_player() == self._player_id:
      # Counterfactual reach probabilities exclude the best-responder's actions,
      # hence return probability 1.0 for every action.
      return [(action, 1.0) for action in state.legal_actions()]
    elif state.is_chance_node():
      return state.chance_outcomes()
    else:
      return list(self._policy.action_probabilities(state).items())

  @_memoize_method
  def value(self, state):
    """Returns the value of the specified state to the best-responder."""
    self.expanded_infostates += 1
    noise = random.random() * eps/2 - eps if self._add_noise else 0
    if state.is_terminal():
      return state.player_return(self._player_id) + noise
    elif state.current_player() == self._player_id:
      action = self.best_response_action(
          state.information_state_string(self._player_id))
      return self.q_value(state, action) + noise
    else:
      return sum(p * self.q_value(state, a) for a, p in self.transitions(state)
                 if p > self._cut_threshold) + noise

  def q_value(self, state, action):
    """Returns the value of the (state, action) to the best-responder."""
    return self.value(state.child(action))

  @_memoize_method
  def best_response_action(self, infostate):
    """Returns the best response for this information state."""
    infoset = self.infosets[infostate]
    # Get actions from the first (state, cf_prob) pair in the infoset list.
    # Return the best action by counterfactual-reach-weighted state-value.
    return max(
        infoset[0][0].legal_actions(),
        key=lambda a: sum(cf_p * self.q_value(s, a) for s, cf_p in infoset))

  def action_probabilities(self, state, player_id=None):
    """Returns the policy for a player in a state.

    Args:
      state: A `pyspiel.State` object.
      player_id: Optional, the player id for whom we want an action. Optional
        unless this is a simultaneous state at which multiple players can act.

    Returns:
      A `dict` of `{action: probability}` for the specified player in the
      supplied state.
    """
    if player_id is None:
      player_id = state.current_player()
    return {
        self.best_response_action(state.information_state_string(player_id)): 1
    }


class CPPBestResponsePolicy(openspiel_policy.Policy):
  """Computes best response action_probabilities using open_spiel's C++ backend.

     May have better performance than best_response.py for large games.
  """

  def __init__(self,
               game,
               best_responder_id,
               policy,
               all_states=None,
               state_to_information_state=None,
               best_response_processor=None,
               cut_threshold=0.0):
    """Constructor.

    Args:
      game: The game to analyze.
      best_responder_id: The player id of the best-responder.
      policy: A policy.Policy object representing the joint policy, taking a
        state and returning a list of (action, probability) pairs. This could be
        aggr_policy, for instance.
      all_states: The result of calling get_all_states.get_all_states. Cached
        for improved performance.
      state_to_information_state: A dict mapping str(state) to
        state.information_state for every state in the game. Cached for improved
        performance.
      best_response_processor: A TabularBestResponse object, used for processing
        the best response actions.
      cut_threshold: The probability to cut when calculating the value.
        Increasing this value will trade off accuracy for speed.
    """
    (self.all_states, self.state_to_information_state) = (
        compute_states_and_info_states_if_none(
            game, all_states, state_to_information_state))

    policy_to_dict = policy_utils.policy_to_dict(
        policy, game, self.all_states, self.state_to_information_state)

    # pylint: disable=g-complex-comprehension
    # Cache TabularBestResponse for players, due to their costly construction
    # TODO(b/140426861): Use a single best-responder once the code supports
    # multiple player ids.
    if not best_response_processor:
      best_response_processor = pyspiel.TabularBestResponse(
          game, best_responder_id, policy_to_dict)

    self._policy = policy
    self.game = game
    self.best_responder_id = best_responder_id
    self.tabular_best_response_map = (
        best_response_processor.get_best_response_actions())

    self._cut_threshold = cut_threshold

  def decision_nodes(self, parent_state):
    """Yields a (state, cf_prob) pair for each descendant decision node."""
    if not parent_state.is_terminal():
      if parent_state.current_player() == self.best_responder_id:
        yield (parent_state, 1.0)
      for action, p_action in self.transitions(parent_state):
        for state, p_state in self.decision_nodes(parent_state.child(action)):
          yield (state, p_state * p_action)

  def transitions(self, state):
    """Returns a list of (action, cf_prob) pairs from the specified state."""
    if state.current_player() == self.best_responder_id:
      # Counterfactual reach probabilities exclude the best-responder's actions,
      # hence return probability 1.0 for every action.
      return [(action, 1.0) for action in state.legal_actions()]
    elif state.is_chance_node():
      return state.chance_outcomes()
    else:
      return list(self._policy.action_probabilities(state).items())

  @_memoize_method
  def value(self, state):
    """Returns the value of the specified state to the best-responder."""
    if state.is_terminal():
      return state.player_return(self.best_responder_id)
    elif state.current_player() == self.best_responder_id:
      action = self.best_response_action(
          state.information_state_string(self.best_responder_id))
      return self.q_value(state, action)
    else:
      return sum(p * self.q_value(state, a) for a, p in self.transitions(state)
                 if p > self._cut_threshold)

  def q_value(self, state, action):
    """Returns the value of the (state, action) to the best-responder."""
    return self.value(state.child(action))

  @_memoize_method
  def best_response_action(self, infostate):
    """Returns the best response for this information state."""
    action = self.tabular_best_response_map[infostate]
    return action

  def action_probabilities(self, state, player_id=None):
    """Returns the policy for a player in a state.

    Args:
      state: A `pyspiel.State` object.
      player_id: Optional, the player id for whom we want an action. Optional
        unless this is a simultabeous state at which multiple players can act.

    Returns:
      A `dict` of `{action: probability}` for the specified player in the
      supplied state.
    """
    # Send the best-response probabilities for the best-responder
    if state.current_player() == self.best_responder_id:
      probs = {action_id: 0. for action_id in state.legal_actions()}
      info_state = self.state_to_information_state[state.history_str()]
      probs[self.tabular_best_response_map[info_state]] = 1.
      return probs

    # Send the default probabilities for all other players
    return self._policy.action_probabilities(state, player_id)

  @property
  def policy(self):
    return self._policy

  def copy_with_noise(self, alpha=0.0, beta=0.0):
    """Copies this policy and adds noise, making it a Noisy Best Response.

    The policy's new probabilities P' on each state s become
    P'(s) = alpha * epsilon + (1-alpha) * P(s)

    With P the former policy's probabilities, and epsilon ~ Softmax(beta *
    Uniform)

    Args:
      alpha: First mixture component
      beta: Softmax 1/temperature component

    Returns:
      Noisy copy of best response.
    """
    return noisy_policy.NoisyPolicy(self, alpha, beta, self.all_states)
