#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

key_input="${SSH_KEY_INPUT:-/run/ssh/root.pub}"
key_target="/root/.ssh/authorized_keys"

install -d -m 0755 -o root -g root /run/sshd
install -d -m 0700 -o root -g root /run/ssh /root/.ssh

# Generate server host keys. These are unrelated to the user's client key pair.
ssh-keygen -A

if [[ -n "${SSH_PUBLIC_KEY:-}" ]]; then
    printf '%s\n' "${SSH_PUBLIC_KEY}" > "${key_input}"
fi

if [[ ! -s "${key_target}" ]]; then
    echo "Waiting for a public key at ${key_input} ..."
    until [[ -s "${key_input}" ]]; do
        sleep 1
    done

    install -m 0600 -o root -g root "${key_input}" "${key_target}"
fi

chown root:root "${key_target}"
chmod 0600 "${key_target}"

echo "Public key ready; starting managed services."
exec /usr/bin/supervisord -n -c /etc/supervisor/supervisord.conf
