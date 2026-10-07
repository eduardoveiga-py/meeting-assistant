// SPDX-License-Identifier: GPL-2.0-or-later
// Reuses OBS libobs-winrt's GPU capture/render backend. That backend calls
// IGraphicsCaptureItemInterop::CreateForWindow(HWND), never a title matcher.
// No pixels cross Python, no monitor capture, no window activation or audio.
#include <windows.h>
#include <dwmapi.h>
#include <obs-module.h>
#include <winrt-capture.h>
#include <algorithm>
#include <mutex>
#include <sstream>
#include "binding_policy.hpp"

namespace {
#define OBS_FUNCTIONS(X) \
    X(obs_register_source_s) X(obs_data_get_string) X(obs_data_get_int) \
    X(obs_properties_create) X(obs_properties_add_list) X(obs_property_list_add_string) \
    X(obs_property_set_enabled) X(obs_enter_graphics) X(obs_leave_graphics) X(obs_queue_task)
#define DECLARE_OBS(name) decltype(&name) p_##name = nullptr;
OBS_FUNCTIONS(DECLARE_OBS)
#undef DECLARE_OBS
#define WINRT_FUNCTIONS(X) \
    X(winrt_capture_supported) X(winrt_capture_init_window) X(winrt_capture_free) \
    X(winrt_capture_active) X(winrt_capture_render) X(winrt_capture_width) X(winrt_capture_height)
#define DECLARE_WINRT(name) decltype(&name) p_##name = nullptr;
WINRT_FUNCTIONS(DECLARE_WINRT)
#undef DECLARE_WINRT
HMODULE winrt_module = nullptr;

uint64_t number(const char* text) {
    if (!text || !*text) return 0;
    char* end = nullptr;
    const auto value = _strtoui64(text, &end, 10);
    return end && *end == 0 && *text != '-' ? value : 0;
}
std::wstring wide(const char* text) {
    if (!text || !*text) return {};
    const int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, nullptr, 0);
    if (!count) return {};
    std::wstring value(count, L'\0');
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, text, -1, value.data(), count);
    value.resize(count - 1);
    return value;
}
bool process(DWORD pid, uint64_t& created, std::wstring& executable) {
    HANDLE handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    if (!handle) return false;
    FILETIME birth{}, exit{}, kernel{}, user{};
    wchar_t path[32768]; DWORD length = 32768;
    const bool ok = GetProcessTimes(handle, &birth, &exit, &kernel, &user)
        && QueryFullProcessImageNameW(handle, 0, path, &length);
    CloseHandle(handle);
    if (!ok) return false;
    created = (static_cast<uint64_t>(birth.dwHighDateTime) << 32) | birth.dwLowDateTime;
    executable.assign(path, length);
    const auto slash = executable.find_last_of(L"\\/");
    if (slash != std::wstring::npos) executable.erase(0, slash + 1);
    return true;
}
ma_jwl::Observed observe(const ma_jwl::Identity& id) {
    ma_jwl::Observed actual;
    HWND window = reinterpret_cast<HWND>(id.hwnd);
    HWND child = reinterpret_cast<HWND>(id.jwl_hwnd);
    if (!window || !child || !IsWindow(window) || !IsWindow(child)) return actual;
    actual.exists = true; actual.hwnd = id.hwnd; actual.jwl_hwnd = id.jwl_hwnd;
    DWORD frame_pid = 0, child_pid = 0;
    GetWindowThreadProcessId(window, &frame_pid);
    GetWindowThreadProcessId(child, &child_pid);
    actual.pid = frame_pid; actual.jwl_pid = child_pid;
    std::wstring frame_exe, child_exe;
    if (!process(actual.pid, actual.created, frame_exe)
        || !process(actual.jwl_pid, actual.jwl_created, child_exe)) return actual;
    actual.jwl_process = _wcsicmp(child_exe.c_str(), L"JWLibrary.exe") == 0
        && (_wcsicmp(frame_exe.c_str(), L"JWLibrary.exe") == 0
            || _wcsicmp(frame_exe.c_str(), L"ApplicationFrameHost.exe") == 0);
    actual.related = window == child || IsChild(window, child);
    wchar_t class_name[256]{};
    GetClassNameW(window, class_name, 256); actual.class_name = class_name;
    actual.visible = IsWindowVisible(window); actual.minimized = IsIconic(window);
    DWORD cloak = 1;
    actual.cloaked = FAILED(DwmGetWindowAttribute(window, DWMWA_CLOAKED, &cloak, sizeof(cloak))) || cloak;
    MONITORINFO info{sizeof(info)};
    const auto monitor = MonitorFromWindow(window, MONITOR_DEFAULTTONULL);
    if (!monitor || !GetMonitorInfoW(monitor, &info)) return actual;
    actual.non_primary = !(info.dwFlags & MONITORINFOF_PRIMARY);
    actual.left = info.rcMonitor.left; actual.top = info.rcMonitor.top;
    actual.right = info.rcMonitor.right; actual.bottom = info.rcMonitor.bottom;
    RECT rect{};
    if (!GetWindowRect(window, &rect)) return actual;
    const int width = std::max(0L, std::min(rect.right, info.rcMonitor.right) - std::max(rect.left, info.rcMonitor.left));
    const int height = std::max(0L, std::min(rect.bottom, info.rcMonitor.bottom) - std::max(rect.top, info.rcMonitor.top));
    const double area = static_cast<double>(info.rcMonitor.right - info.rcMonitor.left) * (info.rcMonitor.bottom - info.rcMonitor.top);
    actual.covers_hall = area > 0 && static_cast<double>(width) * height / area >= 0.85;
    return actual;
}
struct Capture {
    std::mutex mutex;
    ma_jwl::Identity requested, bound;
    bool pending = true;
    struct winrt_capture* capture = nullptr;
    std::string state = "unbound";
    uint32_t width = 0, height = 0;
    float check_timer = 1, retry_timer = 1;
};
void update(void* data, obs_data_t* settings) {
    auto* capture = static_cast<Capture*>(data);
    ma_jwl::Identity id;
    id.hwnd = number(p_obs_data_get_string(settings, "hwnd"));
    id.pid = static_cast<DWORD>(p_obs_data_get_int(settings, "pid"));
    id.created = number(p_obs_data_get_string(settings, "created"));
    id.jwl_hwnd = number(p_obs_data_get_string(settings, "jwl_hwnd"));
    id.jwl_pid = static_cast<DWORD>(p_obs_data_get_int(settings, "jwl_pid"));
    id.jwl_created = number(p_obs_data_get_string(settings, "jwl_created"));
    id.class_name = wide(p_obs_data_get_string(settings, "window_class"));
    id.left = static_cast<int>(p_obs_data_get_int(settings, "hall_left"));
    id.top = static_cast<int>(p_obs_data_get_int(settings, "hall_top"));
    id.right = static_cast<int>(p_obs_data_get_int(settings, "hall_right"));
    id.bottom = static_cast<int>(p_obs_data_get_int(settings, "hall_bottom"));
    const std::string session = p_obs_data_get_string(settings, "session");
    // Keep the status JSON unambiguous. Session tokens are ASCII UUID hex.
    if (session.size() == 32 && session.find_first_not_of("0123456789abcdef") == std::string::npos)
        id.session = session;
    std::lock_guard<std::mutex> lock(capture->mutex);
    capture->requested = std::move(id); capture->pending = true;
    capture->state = "waiting"; capture->width = capture->height = 0;
}
void* create(obs_data_t* settings, obs_source_t*) {
    auto* capture = new Capture;
    update(capture, settings); return capture;
}
void release_capture(Capture* capture) {
    if (capture->capture) p_winrt_capture_free(capture->capture);
    capture->capture = nullptr; capture->width = capture->height = 0;
}
void tick(void* data, float seconds) {
    auto* capture = static_cast<Capture*>(data);
    // Always graphics -> mutex, including destruction. Properties only read
    // cached dimensions, so they never invert OBS's graphics lock ordering.
    p_obs_enter_graphics();
    {
        std::lock_guard<std::mutex> lock(capture->mutex);
        capture->check_timer += seconds; capture->retry_timer += seconds;
        if (capture->pending) {
            release_capture(capture); capture->bound = capture->requested;
            capture->pending = false; capture->check_timer = capture->retry_timer = 1;
        }
        if (capture->check_timer >= 0.25f) {
            capture->check_timer = 0;
            if (!ma_jwl::matches(capture->bound, observe(capture->bound))) {
                release_capture(capture);
                capture->state = capture->bound.hwnd ? "invalid_target" : "unbound";
            } else if (!capture->capture && capture->retry_timer >= 1) {
                capture->retry_timer = 0;
                capture->capture = p_winrt_capture_init_window(FALSE, reinterpret_cast<HWND>(capture->bound.hwnd), TRUE, TRUE);
                capture->state = capture->capture ? "waiting" : "capture_failed";
            }
        }
        if (capture->capture) {
            if (!p_winrt_capture_active(capture->capture)) {
                release_capture(capture); capture->state = "capture_failed";
            } else {
                capture->width = p_winrt_capture_width(capture->capture);
                capture->height = p_winrt_capture_height(capture->capture);
                capture->state = capture->width && capture->height ? "active" : "waiting";
            }
        }
    }
    p_obs_leave_graphics();
}
bool window_still_bound(Capture* capture) {
    if (capture->pending || capture->state != "active") return false;
    DWORD pid = 0;
    HWND window = reinterpret_cast<HWND>(capture->bound.hwnd);
    return IsWindow(window) && GetWindowThreadProcessId(window, &pid)
        && pid == capture->bound.pid && IsWindowVisible(window) && !IsIconic(window);
}
void render(void* data, gs_effect_t*) {
    auto* capture = static_cast<Capture*>(data);
    std::lock_guard<std::mutex> lock(capture->mutex);
    if (window_still_bound(capture) && capture->capture && p_winrt_capture_active(capture->capture))
        p_winrt_capture_render(capture->capture);
}
uint32_t width(void* data) { auto* c = static_cast<Capture*>(data); std::lock_guard<std::mutex> l(c->mutex); return c->width; }
uint32_t height(void* data) { auto* c = static_cast<Capture*>(data); std::lock_guard<std::mutex> l(c->mutex); return c->height; }
void actual_destroy(void* data) { auto* c = static_cast<Capture*>(data); release_capture(c); delete c; }
void destroy(void* data) { p_obs_queue_task(OBS_TASK_GRAPHICS, actual_destroy, data, false); }
const char* name(void*) { return "Meeting Assistant - JWL por HWND"; }
obs_properties_t* properties(void* data) {
    auto* props = p_obs_properties_create();
    auto* item = p_obs_properties_add_list(props, "__ma_capture_status", "Status da captura JWL", OBS_COMBO_TYPE_LIST, OBS_COMBO_FORMAT_STRING);
    std::ostringstream json;
    if (data) {
        auto* c = static_cast<Capture*>(data);
        std::lock_guard<std::mutex> lock(c->mutex);
        const auto& id = c->bound;
        const bool valid = !c->pending && ma_jwl::matches(id, observe(id));
        const std::string state = c->pending ? "waiting" : valid ? c->state : "invalid_target";
        json << "{\"protocol\":1,\"state\":\"" << state << "\",\"hwnd\":\"" << id.hwnd
            << "\",\"pid\":" << id.pid << ",\"created\":\"" << id.created
            << "\",\"jwl_hwnd\":\"" << id.jwl_hwnd << "\",\"jwl_pid\":" << id.jwl_pid
            << ",\"jwl_created\":\"" << id.jwl_created << "\",\"session\":\"" << id.session
            << "\",\"width\":" << c->width << ",\"height\":" << c->height << "}";
    } else json << "{\"protocol\":1,\"state\":\"unbound\"}";
    p_obs_property_list_add_string(item, "Gerenciada pelo Meeting Assistant (consulte os diagnósticos no app)", json.str().c_str());
    p_obs_property_set_enabled(item, false);
    return props;
}
}
#define MA_EXPORT extern "C" __declspec(dllexport)
MA_EXPORT void obs_module_set_pointer(obs_module_t*) {}
MA_EXPORT uint32_t obs_module_ver() { return LIBOBS_API_VER; }
MA_EXPORT const char* obs_module_name() { return "Meeting Assistant JWL HWND Capture"; }
MA_EXPORT const char* obs_module_description() { return "Exact JWL secondary HWND capture using the OBS Windows Graphics Capture backend."; }
MA_EXPORT bool obs_module_load() {
    const auto obs = GetModuleHandleW(L"obs.dll");
    if (!obs) return false;
#define LOAD_OBS(name) p_##name = reinterpret_cast<decltype(p_##name)>(GetProcAddress(obs, #name)); if (!p_##name) return false;
    OBS_FUNCTIONS(LOAD_OBS)
#undef LOAD_OBS
    wchar_t path[32768]{};
    if (!GetModuleFileNameW(nullptr, path, 32768)) return false;
    std::wstring backend(path);
    backend.erase(backend.find_last_of(L"\\/") + 1); backend += L"libobs-winrt.dll";
    winrt_module = LoadLibraryExW(backend.c_str(), nullptr, LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_DEFAULT_DIRS);
    if (!winrt_module) return false;
#define LOAD_WINRT(name) p_##name = reinterpret_cast<decltype(p_##name)>(GetProcAddress(winrt_module, #name)); if (!p_##name) { FreeLibrary(winrt_module); winrt_module = nullptr; return false; }
    WINRT_FUNCTIONS(LOAD_WINRT)
#undef LOAD_WINRT
    if (!p_winrt_capture_supported()) { FreeLibrary(winrt_module); winrt_module = nullptr; return false; }
    obs_source_info info{};
    info.id = "meeting_assistant_jwl_capture"; info.type = OBS_SOURCE_TYPE_INPUT;
    info.output_flags = OBS_SOURCE_VIDEO | OBS_SOURCE_CUSTOM_DRAW | OBS_SOURCE_SRGB;
    info.get_name = name; info.create = create; info.destroy = destroy; info.update = update;
    info.video_tick = tick; info.video_render = render; info.get_width = width; info.get_height = height;
    info.get_properties = properties; info.icon_type = OBS_ICON_TYPE_WINDOW_CAPTURE;
    p_obs_register_source_s(&info, sizeof(info)); return true;
}
MA_EXPORT void obs_module_unload() { if (winrt_module) { FreeLibrary(winrt_module); winrt_module = nullptr; } }
