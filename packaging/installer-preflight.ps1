$ErrorActionPreference = 'Stop'
# The installer never terminates another application's process.
if (Get-Process MeetingAssistant,obs64,WhatsApp,meeting-assistant-camera -ErrorAction SilentlyContinue) {
    exit 2
}
exit 0
