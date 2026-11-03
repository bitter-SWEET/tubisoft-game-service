<?php
// XIII local lab entry point. Port 80 belongs to the existing Apache service.
// Keep this response in sync with compose.yaml's bootstrap configuration.
if (($_GET['dp'] ?? '') !== 'XIIIPS2US') {
    http_response_code(404);
    header('Connection: close');
    exit;
}
$ip = getenv('TUBISOFT_ADVERTISE_IP');
if (!filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4) || $ip === '0.0.0.0') {
    http_response_code(503);
    exit;
}
$body = "routerip0=$ip\r\nrouterport0=30000\r\nrouterlauncherport0=30001\r\nnatserverip0=$ip\r\nnatserverport0=30002\r\n";
header('Content-Type: text/plain');
header('Content-Length: ' . strlen($body));
header('Connection: close');
echo $body;
