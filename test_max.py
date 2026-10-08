import win32gui, win32con, time, os

def test():
    hwnd = win32gui.FindWindow('Notepad', None)
    if not hwnd:
        os.system('start notepad')
        time.sleep(1)
        hwnd = win32gui.FindWindow('Notepad', None)
    if not hwnd:
        print('No notepad')
        return
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    time.sleep(1)
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    placement = win32gui.GetWindowPlacement(hwnd)
    print(f'Maximized style: {style & win32con.WS_MAXIMIZE > 0}, showCmd: {placement[1]}')
    # Strip maximize
    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style & ~win32con.WS_MAXIMIZE)
    win32gui.SetWindowPos(hwnd, 0, 0, 0, 500, 500, win32con.SWP_NOMOVE | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED)
    time.sleep(1)
    style2 = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    print(f'Stripped style: {style2 & win32con.WS_MAXIMIZE > 0}')
    # Restore placement
    win32gui.SetWindowPlacement(hwnd, placement)
    time.sleep(1)
    style3 = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    print(f'Restored style: {style3 & win32con.WS_MAXIMIZE > 0}')
test()
