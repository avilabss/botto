fmt:
    uv run ruff format .
    uv run ruff check --fix .

label-studio-perms:
    mkdir -p data/label-studio
    chmod -R u+rwX data/label-studio

label-studio:
    docker compose -f docker/compose/label-studio.yaml up
