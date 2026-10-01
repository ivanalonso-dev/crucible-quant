#!/bin/bash
# instalar.sh - Deja Crucible Quant funcionando 24/7 en el servidor Oracle (Ubuntu).
#   - Bot de suscripciones como servicio (arranca solo y se reinicia si se cae)
#   - Monitor diario a las 10:10 hora de Madrid (cambio de hora automático)
# Uso (en el servidor):  bash ~/crucible/servidor/instalar.sh
set -e
DIR="$HOME/crucible"
cd "$DIR"

if [ ! -f config_telegram.json ]; then
  echo "ERROR: falta config_telegram.json en $DIR (cópialo desde tu PC)"; exit 1
fi
if [ ! -f parametros.py ]; then
  echo "AVISO: falta parametros.py (umbrales privados). Se usarán los de EJEMPLO de parametros_ejemplo.py."
fi

echo "== 1/5 Zona horaria Europe/Madrid"
sudo timedatectl set-timezone Europe/Madrid

echo "== Memoria extra (swap 2 GB, para servidores pequeños de 1 GB)"
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile > /dev/null && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab > /dev/null
fi

echo "== 2/5 Python"
sudo apt-get update -y -qq
sudo apt-get install -y -qq python3-venv python3-pip sqlite3

echo "== 3/5 Librerías"
python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install -q --upgrade pip
"$DIR/venv/bin/pip" install -q requests pandas numpy pyarrow pillow

echo "== 4/5 Bot como servicio 24/7"
sudo tee /etc/systemd/system/crucible-bot.service > /dev/null <<EOF
[Unit]
Description=Crucible Quant - bot de suscripciones
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python -u $DIR/crucible_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now crucible-bot
sudo systemctl restart crucible-bot

echo "== 5/5 Monitor diario 10:10 (Madrid)"
LINEA="10 10 * * * cd $DIR && $DIR/venv/bin/python crucible_monitor.py >> $DIR/monitor_log.txt 2>&1"
LINEA2="30 10 * * 0 cd $DIR && $DIR/venv/bin/python resumen_semanal.py >> $DIR/resumen_log.txt 2>&1"
( crontab -l 2>/dev/null | grep -v crucible_monitor.py | grep -v resumen_semanal.py ; echo "$LINEA" ; echo "$LINEA2" ) | crontab -

sleep 3
echo ""
echo "================ LISTO ================"
systemctl is-active crucible-bot && echo "Bot: funcionando"
echo "Monitor programado: todos los días a las 10:10 (hora de Madrid)"
echo "Resumen semanal para X: domingos a las 10:30"
echo "Ver el bot en directo:   journalctl -u crucible-bot -f"
echo "Probar el monitor ahora: cd ~/crucible && venv/bin/python crucible_monitor.py"
