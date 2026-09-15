# RC.14 V4 offline benchmark + build tooling

Tooling branch for the RC.14 Agent Catch-Up V4 offline engineering package.
Based on the candidate revision recorded in `V4_SOURCE_COMMIT.txt`.

This directory is **not** part of the candidate image; the candidate build
context is `candidate/rc14-agent-catchup-v4` (repo root) alone.

* `replay_harness_v4.py` - offline replay harness for the V4 arm
  (batch 400 + long-lived writer). Never contacts production Core; refuses the
  production consumer id; hard-blocks `/v1/send/text` with HTTP 409.
* `build_v4.sh`         - clone the candidate branch and build the image.
* `qual_v4.sh`          - run the full test suite inside the built image.
* `bench_matrix.sh`     - 3x V3 arm + 3x V4 arm, interleaved, same workload.
