# DiskWatcher
Monitors the SMART values of your hard drives for signs of tampering (removal without your knowledge).  Works by checking the continuity of the SMART Power Cycle values. 

## Installation - Automatic
Download the whole repo.
```chmod +x installer; ./installer``` to run the installer on APT based systems. 

## Configuration
The app related configuration can be found under ```/etc/default/diskwatcher```.
```ini

# Setting this to
# 0 = Will only show log balloons when something is off.
# 0 = Recommended in hostile environments where the potential attacker may see your display.
# 0 = Recommended once you got familiar with the notify events.
# 1 = Always shows notify balloons
ALWAYS_NOTIFY=1
```

## Installation - Manual
Install the python requirements:
```bash
pip install -r requirements.txt
```

**AS ROOT**: 
```python
# Copy over the files from the _ directory.
cp -a _/* /
#!!! replace %UID% and %NAME% placeholders inside /etc/systemd/system/diskwatcher.service 
#Example: %UID% = 1000, %NAME% = joe

# Reload systemd to scan for new unit files
systemctl daemon-reload
# enable+start the services
systemctl enable diskwatcher
systemctl start diskwatcher
systemctl enable diskwatcher_fetcher
systemctl start diskwatcher_fetcher

chmod 555 /opt/diskwatcher/diskwatcher
chmod 500 /opt/diskwatcher/diskwatcher_fetcher

# enjoy!
```
