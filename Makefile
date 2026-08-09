# Root convenience wrapper: the real Makefile lives in bot_globa/.
# `make check` at the repo root behaves exactly like `make check` there.

APP_DIR := bot_globa

.DEFAULT_GOAL := help

.PHONY: help
help:
	@$(MAKE) -s -C $(APP_DIR) help

# Forward every other target (and its variables) to the app Makefile.
%:
	@$(MAKE) -C $(APP_DIR) $@
