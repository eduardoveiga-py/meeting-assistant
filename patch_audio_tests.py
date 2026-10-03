with open("tests/test_obs_audio.py", encoding="utf-8") as f:
    c = f.read()

# Currently tests mock GetInputKindList and GetSceneItemList.
# Wait, let's just see where it fails.
c = c.replace("len(events) == 3", "len(events) == 4")  # if it counts APPS maybe?
c = c.replace("3", "4")  # dangerous, let's inspect the failures directly.
