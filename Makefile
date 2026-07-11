PYTHON ?= python3
MAPSI_REPO ?= mapsi/mapsi-v6
MAPSI_CONTRACT_PATH ?= docs/growth-contract/published
MAPSI_REF_TYPE ?=
MAPSI_REF ?=

.PHONY: contracts-sync contracts-check mapsi-mock mautic-mock ovh-up ovh-down

contracts-sync:
	@test -n "$(MAPSI_REF_TYPE)" || (echo "MAPSI_REF_TYPE is required: tag|branch|sha" && exit 1)
	@test -n "$(MAPSI_REF)" || (echo "MAPSI_REF is required" && exit 1)
	$(PYTHON) scripts/sync_mapsi_contract.py --repo $(MAPSI_REPO) --contract-path $(MAPSI_CONTRACT_PATH) --$(MAPSI_REF_TYPE) $(MAPSI_REF)

contracts-check:
	$(PYTHON) scripts/check_mapsi_contract.py
	pytest tests/contracts

mapsi-mock:
	uvicorn app.mock_mapsi_server:app --host 0.0.0.0 --port 8010

mautic-mock:
	uvicorn app.mock_mautic_server:app --host 0.0.0.0 --port 8020

ovh-up:
	docker compose -f docker-compose.ovh.yml up -d --build

ovh-down:
	docker compose -f docker-compose.ovh.yml down
