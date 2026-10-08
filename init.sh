#!/bin/sh
# Creates an Agentic Project from this template, in place (see setup/INIT.md):
#   ./init.sh --name NAME --language ru|en --profile software|generic --agents claude,codex --yes
# Windows: init.cmd with the same arguments.
unset CDPATH
case $0 in
  */*) dir=${0%/*} ;;
  *\\*) dir=${0%\\*} ;;
  *) dir=. ;;
esac
cd -P -- "${dir:-/}" || exit 1
TB_ROOT=$(pwd -P)
export TB_ROOT
exec sh payload/modules/core/Toolbox/tb run setup/init.py "$@"
