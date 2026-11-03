<?php
// Optional Apache/PHP bridge to the canonical Python bootstrap dispatcher.
// Product formats and enabled titles live only in the application profiles.
$product = $_GET['dp'] ?? '';
if (!is_string($product) || !preg_match('/^[A-Z0-9]{1,64}$/D', $product)) {
    http_response_code(404);
    header('Connection: close');
    exit;
}
$context = stream_context_create(['http' => ['timeout' => 3, 'ignore_errors' => true,
    'follow_location' => 0, 'header' => "Connection: close\r\n"]]);
$body = @file_get_contents('http://127.0.0.1:18080/gsinit.php?dp=' . rawurlencode($product), false, $context);
if ($body === false || !isset($http_response_header[0])) {
    http_response_code(503);
    exit;
}
if (!preg_match('/^HTTP\/\S+ (\d{3})/', $http_response_header[0], $status)) {
    http_response_code(503);
    exit;
}
http_response_code((int)$status[1]);
header('Content-Type: text/plain');
header('Content-Length: ' . strlen($body));
header('Connection: close');
echo $body;
