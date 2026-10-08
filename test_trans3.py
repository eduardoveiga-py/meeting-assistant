import obsws_python as obs
client = obs.ReqClient(host='localhost', port=4455, password='meeting123')
print(client.send('GetSceneTransitionList').__dict__)
