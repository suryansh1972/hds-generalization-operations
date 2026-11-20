# External data (not committed)

Place local copies of licensed or third-party evidence here (everything except this file and `.gitkeep` is
git-ignored), then point semgen at them with environment variables (see `.env.example`):

| File | Variable | Pinned by |
|---|---|---|
| SNOMED CT RF2 release (any location) | `SEMGEN_RF2_DIR` | release date / fingerprint in every run header |
| `ucum/ucum-essence.xml` (UCUM essence 1.9) | `SEMGEN_UCUM_ESSENCE` | `ucum.sha256` in the config |
| `refrange.sqlite` (Mayo reference ranges) | `SEMGEN_MAYO_DB` | `mayo.sha256` in the config |
| Mayo test map CSV | `SEMGEN_MAYO_TEST_MAP` | its sha256 is recorded in the run header |
