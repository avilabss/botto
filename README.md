# Botto

YOLO-based game automation monorepo.

## Project Layout

```text
.
├── crates/                  # Rust backend, game automation, shared crates, CLIs
├── apps/                    # Non-Rust app shells, such as the frontend
├── ml/                      # Python training, evaluation, dataset-build, inference tooling
├── data/                    # Local/generated data; mostly ignored by git
│   ├── raw/                 # Original captures: screenshots, videos, frame dumps
│   ├── label-studio/        # Label Studio internal state and uploaded files
│   ├── exports/             # Annotation exports from Label Studio
│   ├── datasets/            # YOLO-ready train/val/test datasets
│   ├── models/              # Model weights and exported artifacts
│   └── runs/                # Training/inference outputs
├── docker/
│   ├── compose/             # Compose stacks by purpose: dev, prod, labeling, training
│   ├── env/                 # Compose env files and checked-in examples
│   └── images/              # Dockerfiles grouped by image
├── infra/                   # Deployment automation: Ansible, host config, provisioning
├── scripts/                 # Thin project commands that orchestrate app/ml/infra code
└── compose.yaml             # Default local compose entry point
```

Top-level directories should represent ownership boundaries. If a file belongs to
the Rust backend, core game automation, screen/control loop, or Rust CLI tools,
put it in `crates/`. If it belongs to the frontend or another non-Rust runnable
app, put it in `apps/`. If it is model-training or dataset pipeline code, put it
in `ml/`. If it describes how the project runs in containers, put it in
`docker/`. If it deploys machines or services, put it in `infra/`.

Expected Rust workspace shape once implementation starts:

```text
crates/
├── botto-core/              # Shared domain types, config, errors
├── botto-automation/        # Game observation, decision loop, input control
├── botto-api/               # Backend API/server
└── botto-cli/               # Local operator commands
```

Avoid putting Rust code in a top-level `src/` directory once this becomes a
workspace. Reserve `ml/` for Python/YOLO tooling and keep the runtime product in
Rust.

## Label Studio

The Label Studio stack lives in `docker/compose/label-studio.yaml` and stores its
runtime data in `data/label-studio`.

```bash
docker compose -f docker/compose/label-studio.yaml up -d
```

The container is configured to run as UID/GID `1000:1000`, matching the default
local Linux user that owns this repo. If your user has a different UID/GID, start
it with overrides:

```bash
LABEL_STUDIO_UID=$(id -u) LABEL_STUDIO_GID=$(id -g) docker compose -f docker/compose/label-studio.yaml up
```

If the data directory itself is missing owner write permissions, run:

```bash
just label-studio-perms
```

Annotation exports should go under `data/exports`, then converted YOLO datasets
should go under `data/datasets`.
