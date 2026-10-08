import json
from meeting_assistant.services.obs_websocket import connect
client = connect('localhost', 4455, 'meeting123')
print(json.dumps(client.send('GetSceneTransitionList', raw=True), indent=2))
