import ctypes
from ctypes import wintypes
import threading
from PyQt6.QtCore import QObject, pyqtSignal

# Win32 Constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

VK_S = 0x53
VK_O = 0x4F
VK_Z = 0x5A
VK_CONTROL = 0x11
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3

LLKHF_INJECTED = 0x0010

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.HINSTANCE, wintypes.DWORD]

user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

user32.CallNextHookEx.restype = ctypes.c_long
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]

LowLevelKeyboardProc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

class HotkeyWorker(QObject):
    """
    Dedicated Win32 Low-Level Keyboard Hook for OCR hotkeys:
    - Ctrl + Alt + S: Trigger single screen scan & translation
    - Ctrl + Alt + Z: Open interactive screen zone selector
    - Ctrl + Alt + O: Toggle real-time background auto-scan
    """

    scan_triggered = pyqtSignal()
    select_zone_triggered = pyqtSignal()
    toggle_auto_triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._hook = None
        self._running = True
        self._proc = LowLevelKeyboardProc(self._low_level_keyboard_proc)

    def _is_key_pressed(self, vk: int) -> bool:
        return bool(user32.GetAsyncKeyState(vk) & 0x8000)

    def _low_level_keyboard_proc(self, nCode, wParam, lParam):
        try:
            if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if kb.flags & LLKHF_INJECTED:
                    return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

                vk = kb.vkCode
                ctrl_pressed = (
                    self._is_key_pressed(VK_CONTROL) or
                    self._is_key_pressed(VK_LCONTROL) or
                    self._is_key_pressed(VK_RCONTROL)
                )
                alt_pressed = bool(user32.GetAsyncKeyState(0x12) & 0x8000)

                if ctrl_pressed and alt_pressed:
                    if vk == VK_S:
                        self.scan_triggered.emit()
                        return 1
                    elif vk == VK_Z:
                        self.select_zone_triggered.emit()
                        return 1
                    elif vk == VK_O:
                        self.toggle_auto_triggered.emit()
                        return 1
        except Exception:
            pass

        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

    def start_hook(self):
        h_mod = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self._proc,
            h_mod,
            0
        )
        if not self._hook:
            print("[WinHook] Failed to install SetWindowsHookEx")
            return

        msg = wintypes.MSG()
        while self._running:
            bRet = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if bRet == 0 or bRet == -1:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def stop_hook(self):
        self._running = False
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None
        user32.PostQuitMessage(0)
