# IO Guard stage-aware character heads v3

This directory contains the small, reproducible classifier heads used by IO
Guard in production. They are trained separately for user input, model output,
and external/tool content. The runtime does not need the 90 MB Transformer v2
weights or network access.

The committed `training_metadata.json` records the selected hyperparameters,
validation/test metrics, dataset hashes, and error analysis. The full academic
datasets are not vendored; rebuild them with
`evaluation/scripts/build_io_guard_stage_dataset.py`, then train with
`evaluation/scripts/train_io_guard_char_heads.py`.

Production threshold overrides are defined in `configs/default_policy.json`:

- input `0.6825`: balanced security threshold; deterministic IO
  Guard rules continue to catch explicit short attacks.
- output `0.30`: held-out recall 100%, false-positive rate 0%; placeholder
  outputs such as `[OTP]` and `[API_KEY]` are trained as safe.
- content `0.70`: held-out recall 98.14%, false-positive rate 0%; tool JSON is
  evaluated per string field rather than as one structural blob.

Do not replace these artifacts without regenerating metadata and running the
academic and project regression suites.
