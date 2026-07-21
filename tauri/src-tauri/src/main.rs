use std::io::{Read, Write};
use std::net::TcpStream;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::Manager;

struct PythonServer(Mutex<Option<Child>>);
fn find_free_port() -> u16 {
    use std::net::TcpListener;
    for port in 8099..8199 {
        if TcpListener::bind(("127.0.0.1", port)).is_ok() {
            return port;
        }
    }
    8099
}

fn find_python() -> (String, Vec<String>) {
    // 1. Bundled PyInstaller binary (production app)
    //    macOS: HIFI Detector.app/Contents/Resources/python/hifi-detect-server
    //    Windows: python/hifi-detect-server.exe (next to the .exe)
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            // macOS bundle: exe is at Contents/MacOS/, resources at ../Resources/python/
            #[cfg(target_os = "macos")]
            {
                let resources = parent.join("../Resources");
                if resources.exists() {
                    if let Ok(entries) = std::fs::read_dir(&resources) {
                        for entry in entries.flatten() {
                            let path = entry.path();
                            if path.is_dir() {
                                let candidate = path.join("hifi-detect-server");
                                if candidate.exists() {
                                    return (candidate.to_string_lossy().to_string(), vec![]);
                                }
                            } else if path
                                .file_name()
                                .map_or(false, |n| n == "hifi-detect-server")
                            {
                                return (path.to_string_lossy().to_string(), vec![]);
                            }
                        }
                    }
                }
            }

            // Windows bundle: python/ is next to the .exe
            #[cfg(target_os = "windows")]
            {
                let bundled = parent.join("python").join("hifi-detect-server.exe");
                if bundled.exists() {
                    return (bundled.to_string_lossy().to_string(), vec![]);
                }
            }
        }
    }

    // 2. PyInstaller output in dist-python (dev testing without venv)
    //    macOS: ../dist-python/hifi-detect-server/hifi-detect-server
    //    Windows: ..\dist-python\hifi-detect-server\hifi-detect-server.exe
    #[cfg(target_os = "windows")]
    let pyinst_dev = "../dist-python/hifi-detect-server/hifi-detect-server.exe";
    #[cfg(not(target_os = "windows"))]
    let pyinst_dev = "../dist-python/hifi-detect-server/hifi-detect-server";

    if std::path::Path::new(pyinst_dev).exists() {
        return (pyinst_dev.to_string(), vec![]);
    }

    // 3. Project venv (dev)
    //    macOS: .venv/bin/python
    //    Windows: .venv\Scripts\python.exe
    let venv_python = {
        #[cfg(target_os = "windows")]
        {
            "../.venv/Scripts/python.exe"
        }
        #[cfg(not(target_os = "windows"))]
        {
            "../../.venv/bin/python"
        }
    };
    if std::path::Path::new(venv_python).exists() {
        return (
            venv_python.to_string(),
            vec![
                "-m".to_string(),
                "hifi_detector.cli".to_string(),
                "web".to_string(),
            ],
        );
    }

    // 4. System fallback
    #[cfg(target_os = "windows")]
    let sys_python = "python";
    #[cfg(not(target_os = "windows"))]
    let sys_python = "python3";

    (
        sys_python.to_string(),
        vec![
            "-m".to_string(),
            "hifi_detector.cli".to_string(),
            "web".to_string(),
        ],
    )
}

fn start_python_server(port: u16) -> Result<Child, String> {
    let (python, base_args) = find_python();

    let child = Command::new(&python)
        .args(&base_args)
        .arg("--no-open")
        .arg("--port")
        .arg(port.to_string())
        .arg("--host")
        .arg("127.0.0.1")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to spawn Python server: {}", e))?;

    Ok(child)
}

fn wait_for_server(port: u16, timeout_secs: u64) -> bool {
    let start = Instant::now();
    while start.elapsed() < Duration::from_secs(timeout_secs) {
        if let Ok(mut stream) = TcpStream::connect_timeout(
            &format!("127.0.0.1:{}", port).parse().unwrap(),
            Duration::from_millis(500),
        ) {
            let _ = stream.write_all(b"GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n");
            let mut buf = [0u8; 1];
            if stream.read(&mut buf).is_ok() {
                return true;
            }
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

fn main() {
    let port = find_free_port();

    // Start Python before Tauri bootstraps
    let server_ok = match start_python_server(port) {
        Ok(child) => {
            if wait_for_server(port, 20) {
                PythonServer(Mutex::new(Some(child)))
            } else {
                eprintln!("Python server did not start on port {}.", port);
                PythonServer(Mutex::new(None))
            }
        }
        Err(e) => {
            eprintln!("Failed to start Python server: {}", e);
            PythonServer(Mutex::new(None))
        }
    };

    let server_running = server_ok.0.lock().unwrap().is_some();

    tauri::Builder::default()
        .manage(server_ok)
        .setup(move |app| {
            if let Some(window) = app.get_webview_window("main") {
                // Force dark title bar on Windows
                let _ = window.set_theme(Some(tauri::Theme::Dark));
                if server_running {
                    let url = format!("http://127.0.0.1:{}", port);
                    let _ = window.navigate(url.parse().unwrap());
                } else {
                    let _ = window.navigate(
                        "data:text/html,<h1 style='color:red;padding:40px;font-family:sans-serif'>Python backend not found.<br><br>Please make sure the PyInstaller binary is bundled correctly.</h1>"
                            .parse()
                            .unwrap(),
                    );
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let state = window.state::<PythonServer>();
                let mut guard = match state.0.lock() {
                    Ok(g) => g,
                    Err(_) => return,
                };
                if let Some(ref mut child) = *guard {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("Failed to launch HIFI Detector");
}
