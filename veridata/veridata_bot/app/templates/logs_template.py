LOGS_HTML = """
<!DOCTYPE html>
<html>
    <head>
        <title>Live Logs - Veridata Bot</title>
        <style>
            body { font-family: monospace; background: #1e1e1e; color: #d4d4d4; margin: 0; padding: 20px; display: flex; flex-direction: column; height: 100vh; box-sizing: border-box; }
            h1 { margin-top: 0; color: #569cd6; font-size: 1.2rem; display: flex; justify-content: space-between; align-items: center; }
            #controls { margin-bottom: 10px; display: flex; gap: 10px; }
            input { background: #3c3c3c; border: 1px solid #555; color: white; padding: 5px; border-radius: 4px; flex-grow: 1; }
            button { background: #0e639c; color: white; border: none; padding: 5px 15px; border-radius: 4px; cursor: pointer; }
            button:hover { background: #1177bb; }
            #logs { flex-grow: 1; overflow-y: auto; background: #000; padding: 10px; border: 1px solid #333; border-radius: 4px; white-space: pre-wrap; word-wrap: break-word; }
            .log-line { border-bottom: 1px solid #222; padding: 2px 0; }
            .filtered { display: none; }
            .highlight { color: #f1fa8c; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>
            <span>Veridata Bot Logs</span>
            <span id="status" style="font-size: 0.8rem; color: #888;">Connecting...</span>
        </h1>
        <div id="controls">
            <input type="text" id="filterInput" placeholder="Filter logs (regex supported)..." onkeyup="applyFilter()">
            <button onclick="clearLogs()">Clear</button>
            <button onclick="toggleAutoScroll()" id="scrollBtn">Auto-scroll: ON</button>
        </div>
        <div id="logs"></div>
        <script>
            var ws = new WebSocket((window.location.protocol === "https:" ? "wss://" : "ws://") + window.location.host + "/ops/logs/ws");
            var logsDiv = document.getElementById("logs");
            var autoScroll = true;
            var filterValue = "";

            ws.onmessage = function(event) {
                var lines = event.data.split('\\n');
                lines.forEach(function(line) {
                    if (!line) return;
                    var div = document.createElement("div");
                    div.className = "log-line";
                    div.textContent = line;
                    logsDiv.appendChild(div);
                });
                applyFilter(); // Re-apply filter to new lines
                if (autoScroll) logsDiv.scrollTop = logsDiv.scrollHeight;
            };

            ws.onopen = function() {
                document.getElementById("status").textContent = "Connected";
                document.getElementById("status").style.color = "#4caf50";
            };

            ws.onclose = function() {
                document.getElementById("status").textContent = "Disconnected";
                document.getElementById("status").style.color = "#f44336";
            };

            function applyFilter() {
                var input = document.getElementById("filterInput").value;
                filterValue = input.toLowerCase();
                var lines = logsDiv.getElementsByClassName("log-line");
                var regex = null;
                try {
                     if (input) regex = new RegExp(input, "i");
                } catch(e) {}

                for (var i = 0; i < lines.length; i++) {
                    var text = lines[i].textContent;
                    if (!input) {
                        lines[i].classList.remove("filtered");
                        continue;
                    }
                    if (regex && regex.test(text)) {
                         lines[i].classList.remove("filtered");
                    } else {
                         lines[i].classList.add("filtered");
                    }
                }
            }

            function clearLogs() {
                logsDiv.innerHTML = "";
            }

            function toggleAutoScroll() {
                autoScroll = !autoScroll;
                document.getElementById("scrollBtn").textContent = "Auto-scroll: " + (autoScroll ? "ON" : "OFF");
                if (autoScroll) logsDiv.scrollTop = logsDiv.scrollHeight;
            }
        </script>
    </body>
</html>
"""
