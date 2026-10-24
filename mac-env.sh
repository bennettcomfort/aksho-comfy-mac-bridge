# Finder opens .command files with a minimal PATH (/usr/bin:/bin).
# uv lives in ~/.local/bin, Homebrew git in /opt/homebrew/bin, and this
# machine's Python 3.13 is a pyenv version. Put those in front.
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:${PATH}"
if [[ -d "${HOME}/.pyenv" ]]; then
  export PYENV_ROOT="${HOME}/.pyenv"
  export PATH="${PYENV_ROOT}/bin:${PATH}"
  if command -v pyenv >/dev/null 2>&1; then
    eval "$(pyenv init - bash)" || true
  fi
fi
