#!/usr/bin/env bash
# Prepara um servidor Ubuntu 24.04 novo para o Belo Vale II. Roda uma vez,
# como root, logo depois de contratar o servidor.
#
#   ssh root@IP 'bash -s' < tools/servidor/preparar-servidor.sh
#
# Faz, nesta ordem:
#
# 1. nome `belo-vale` (o endereço do app sai https://belo-vale.<rede>.ts.net),
#    fuso de São Paulo, pacotes atualizados e atualizações de segurança
#    automáticas;
# 2. 2 GB de swap (a compilação do MinIO pede memória);
# 3. Docker e Docker Compose do repositório oficial (o compose usa `!reset`
#    e `!override`, de versões novas), com registros limitados;
# 4. usuário `belovale`, que roda o sistema, com a mesma chave SSH do root;
# 5. SSH só por chave e sem root — só depois de conferir que o `belovale`
#    tem a chave, para ninguém ficar trancado do lado de fora;
# 6. firewall fechado, só com o SSH aberto: o app atende em 127.0.0.1 e sai
#    para a internet pelo Tailscale Funnel, sem porta aberta;
# 7. Tailscale, rclone (Backblaze), gpg e git.
#
# Pode rodar de novo: cada passo confere o que já existe.

set -euo pipefail

USUARIO=belovale

if [[ "$(id -u)" != "0" ]]; then
  echo "Rode como root." >&2
  exit 1
fi
if [[ ! -s /root/.ssh/authorized_keys ]]; then
  echo "O root não tem chave SSH em /root/.ssh/authorized_keys. Cadastre a chave antes:" >&2
  echo "sem ela, desligar a senha trancaria o servidor." >&2
  exit 1
fi

echo "== 1. Nome, fuso, pacotes e atualizações automáticas"
hostnamectl set-hostname belo-vale
timedatectl set-timezone America/Sao_Paulo
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -yq
apt-get install -yq ca-certificates curl gnupg git ufw unattended-upgrades rclone python3 jq
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== 2. Swap"
if ! swapon --show | grep -q .; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

echo "== 3. Docker (repositório oficial)"
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    >/etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
# Registros dos contêineres com tamanho limitado: sem isto, o disco enche.
cat >/etc/docker/daemon.json <<'JSON'
{ "log-driver": "local", "log-opts": { "max-size": "10m", "max-file": "3" } }
JSON
systemctl enable --now docker
systemctl restart docker

echo "== 4. Usuário $USUARIO"
if ! id "$USUARIO" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "Belo Vale II" "$USUARIO"
fi
usermod -aG docker,sudo "$USUARIO"
# Sem senha no usuário, o sudo também não pede (o acesso já é só por chave).
echo "$USUARIO ALL=(ALL) NOPASSWD:ALL" >/etc/sudoers.d/90-$USUARIO
chmod 440 /etc/sudoers.d/90-$USUARIO
install -d -m 700 -o "$USUARIO" -g "$USUARIO" /home/$USUARIO/.ssh
install -m 600 -o "$USUARIO" -g "$USUARIO" /root/.ssh/authorized_keys /home/$USUARIO/.ssh/authorized_keys

echo "== 5. SSH só por chave, sem root"
cat >/etc/ssh/sshd_config.d/10-belo-vale.conf <<'CONF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
CONF
sshd -t
systemctl reload ssh

echo "== 6. Firewall"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

echo "== 7. Tailscale"
if ! command -v tailscale >/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi

echo
echo "Pronto. A partir de agora, entre como: ssh $USUARIO@$(hostname -I | awk '{print $1}')"
echo "O root e a senha não entram mais. Próximo passo: docs/runbook-producao.md, 'Servidor novo'."
