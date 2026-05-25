.PHONY: help install install-venv install-udev install-config install-service uninstall \
        start stop restart enable disable status logs daemon-reload edit-config

PROJECT_DIR := $(CURDIR)
VENV_PY := $(PROJECT_DIR)/.venv/bin/python
UDEV_RULE_DST := /etc/udev/rules.d/70-jabra-speak510.rules
SYSTEMD_USER_DIR := $(HOME)/.config/systemd/user
SERVICE_DST := $(SYSTEMD_USER_DIR)/jabra-speak510-mute.service
CONFIG_DIR := $(HOME)/.config/jabra-speak510-mute
CONFIG_FILE := $(CONFIG_DIR)/config.env
UNIT := jabra-speak510-mute.service

help:
	@echo "Setup:"
	@echo "  install         set up venv, udev rule, systemd --user unit, default config"
	@echo "  uninstall       reverse install (keeps user config and venv)"
	@echo
	@echo "Service control:"
	@echo "  start           start the service"
	@echo "  stop            stop the service"
	@echo "  restart         restart (use after editing source or config)"
	@echo "  enable          enable autostart at login"
	@echo "  disable         disable autostart"
	@echo "  status          show service status"
	@echo "  logs            follow service logs (Ctrl-C to exit)"
	@echo "  daemon-reload   reload systemd unit files (after editing the unit)"
	@echo
	@echo "Config:"
	@echo "  edit-config     open $(CONFIG_FILE) in \$$EDITOR"

install: install-venv install-udev install-config install-service
	systemctl --user daemon-reload
	systemctl --user enable --now $(UNIT)
	@echo
	@echo "Installed."
	@echo "Edit $(CONFIG_FILE) to set HA_URL / HA_TOKEN / HA_LIGHTS, then: make restart"

install-venv:
	uv sync

install-udev:
	sudo install -m 0644 packaging/70-jabra-speak510.rules $(UDEV_RULE_DST)
	sudo udevadm control --reload
	sudo udevadm trigger

install-config:
	@mkdir -p $(CONFIG_DIR)
	@if [ ! -f $(CONFIG_FILE) ]; then \
		install -m 0600 packaging/config.env.example $(CONFIG_FILE); \
		echo "wrote $(CONFIG_FILE) (edit to enable HA integration)"; \
	else \
		echo "kept existing $(CONFIG_FILE)"; \
	fi

install-service:
	@mkdir -p $(SYSTEMD_USER_DIR)
	sed 's|@VENV_PYTHON@|$(VENV_PY)|g' packaging/jabra-speak510-mute.service > $(SERVICE_DST)

uninstall:
	-systemctl --user disable --now $(UNIT)
	-rm -f $(SERVICE_DST)
	-systemctl --user daemon-reload
	-sudo rm -f $(UDEV_RULE_DST)
	-sudo udevadm control --reload
	@echo "Uninstalled. Kept $(CONFIG_FILE) and $(PROJECT_DIR)/.venv."

# --- service control ---

start:
	systemctl --user start $(UNIT)

stop:
	systemctl --user stop $(UNIT)

restart:
	systemctl --user restart $(UNIT)

enable:
	systemctl --user enable $(UNIT)

disable:
	systemctl --user disable $(UNIT)

status:
	@systemctl --user status $(UNIT) --no-pager || true

logs:
	journalctl --user -u $(UNIT) -f

daemon-reload:
	systemctl --user daemon-reload

# --- convenience ---

edit-config:
	$${EDITOR:-nano} $(CONFIG_FILE)
