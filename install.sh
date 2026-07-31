#!/usr/bin/env bash

cd /root
if [ -f fork-gpt-outlook-register/webui/webui.db ]; then
    cp fork-gpt-outlook-register/webui/webui.db webui.db.backup
fi

if [ -d fork-gpt-outlook-register/.git ]; then
    cd fork-gpt-outlook-register
    git fetch origin linux-service
    git checkout linux-service
    git pull --ff-only origin linux-service
else
    git clone -b linux-service --single-branch https://github.com/giveyousomecolorlooklook/fork-gpt-outlook-register
    cd fork-gpt-outlook-register
fi

uv venv
uv pip install -r requirements.txt

if [ -f /root/webui.db.backup ]; then
    cp /root/webui.db.backup webui/webui.db
fi

cp freetoken.service /etc/systemd/system/freetoken.service
systemctl daemon-reload
systemctl enable freetoken
systemctl start freetoken
