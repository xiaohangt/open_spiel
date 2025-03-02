// Copyright 2019 DeepMind Technologies Ltd. All rights reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "math.h"

#include "open_spiel/games/kuhn_poker.h"

#include "open_spiel/algorithms/get_all_states.h"
#include "open_spiel/policy.h"
#include "open_spiel/spiel_utils.h"
#include "open_spiel/tests/basic_tests.h"

namespace open_spiel {
namespace kuhn_poker {
namespace {

namespace testing = open_spiel::testing;

void BasicKuhnTests() {
  testing::LoadGameTest("k_gmp");
  testing::NoChanceOutcomesTest(*LoadGame("k_gmp"));

//  testing::ChanceOutcomesTest(*LoadGame("k_gmp"));
  testing::RandomSimTest(*LoadGame("k_gmp"), 100);
}

void CountStates() {
  std::shared_ptr<const Game> game = LoadGame("k_gmp");
  auto states = algorithms::GetAllStates(*game, /*depth_limit=*/-1,
                                         /*include_terminals=*/true,
                                         /*include_chance_states=*/false);
  SPIEL_CHECK_EQ(states.size(),   1 + (9) + 9 * (3*3));
}

void PolicyTest() {
  using PolicyGenerator = std::function<TabularPolicy(const Game& game)>;
  std::vector<PolicyGenerator> policy_generators = {
      GetAlwaysPassPolicy,
      GetAlwaysBetPolicy,
  };

  std::shared_ptr<const Game> game = LoadGame("k_gmp");
  for (const auto& policy_generator : policy_generators) {
    testing::TestEveryInfostateInPolicy(policy_generator, *game);
    testing::TestPoliciesCanPlay(policy_generator, *game);
  }
}

}  // namespace
}  // namespace kuhn_poker
}  // namespace open_spiel

int main(int argc, char **argv) {
  open_spiel::kuhn_poker::BasicKuhnTests();
  open_spiel::kuhn_poker::CountStates();
//  open_spiel::kuhn_poker::PolicyTest();
//  open_spiel::testing::CheckChanceOutcomes(*open_spiel::LoadGame(
//      "kuhn_poker", {{"players", open_spiel::GameParameter(3)}}));
  open_spiel::testing::RandomSimTest(*open_spiel::LoadGame("k_gmp"),
                                     /*num_sims=*/10);
//  open_spiel::testing::ResampleInfostateTest(
//      *open_spiel::LoadGame("kuhn_poker"),
//      /*num_sims=*/10);
}
