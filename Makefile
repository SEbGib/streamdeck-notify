.PHONY: install install-plugin bridge enable disable status logs sync

PROJECT_DIR := $(shell pwd)
PLUGIN_DEST := $(HOME)/.var/app/com.core447.StreamController/data/plugins/com_sgiband_NotifyCenter

install:
	bash setup.sh

install-plugin:
	@mkdir -p $(PLUGIN_DEST)
	rsync -av --delete streamcontroller-plugin/ $(PLUGIN_DEST)/
	@echo "Plugin installed to $(PLUGIN_DEST)"

bridge:
	. .venv/bin/activate && python3 -m src.bridge

enable:
	@mkdir -p $(HOME)/.config/systemd/user
	cp systemd/notify-bridge.service $(HOME)/.config/systemd/user/
	systemctl --user daemon-reload
	systemctl --user enable --now notify-bridge
	@echo "Service enabled and started."

disable:
	systemctl --user disable --now notify-bridge
	@echo "Service disabled and stopped."

status:
	@curl -s localhost:9120/status | python3 -m json.tool 2>/dev/null || curl -s localhost:9120/status

logs:
	journalctl --user -u notify-bridge -f

sync:
	@mkdir -p $(PLUGIN_DEST)
	rsync -av --delete streamcontroller-plugin/ $(PLUGIN_DEST)/
	@echo "Plugin synced. Restarting StreamController..."
	flatpak kill com.core447.StreamController 2>/dev/null || true
	flatpak run com.core447.StreamController &
	@echo "StreamController restarted."
