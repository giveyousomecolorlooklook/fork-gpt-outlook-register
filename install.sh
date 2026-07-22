cd /root
git clone -b skip_sms2 --single-branch https://github.com/giveyousomecolorlooklook/fork-gpt-outlook-register
cd fork-gpt-outlook-register
uv venv
uv pip install -r requirements.txt
cp freetoken.service /etc/systemd/system/freetoken.service
systemctl daemon-reload
systemctl enable freetoken
systemctl start freetoken



