# ComfyUI Image Processor API

Base URL: `http://localhost:3169`

## POST /process

Process an image through the ComfyUI sight engine bypasser workflow. Accepts three input modes.

### Mode 1: File Upload

Upload an image file directly using multipart form data.

```bash
curl -X POST -F 'image=@photo.png' http://localhost:3169/process
```

**Content-Type:** `multipart/form-data`

| Field   | Type | Required | Description          |
|---------|------|----------|----------------------|
| `image` | file | yes      | The image file to process |

### Mode 2: Base64

Send a base64-encoded image in a JSON body.

```bash
curl -X POST http://localhost:3169/process \
  -H 'Content-Type: application/json' \
  -d '{"base64": "<base64-encoded-image-data>", "filename": "input.png"}'
```

**Content-Type:** `application/json`

| Field      | Type   | Required | Description                        |
|------------|--------|----------|------------------------------------|
| `base64`   | string | yes      | Base64-encoded image data          |
| `filename` | string | no       | Optional filename (default: `input.png`) |

### Mode 3: URL

Provide a URL to an image. The server downloads it and processes it.

```bash
curl -X POST http://localhost:3169/process \
  -H 'Content-Type: application/json' \
  -d '{"url": "https://example.com/photo.png"}'
```

**Content-Type:** `application/json`

| Field | Type   | Required | Description              |
|-------|--------|----------|--------------------------|
| `url` | string | yes      | Public URL to an image   |

### Success Response

**Status:** `200 OK`

```json
{
  "status": "success",
  "output": "/path/to/output.png",
  "size_bytes": 1234567
}
```

| Field        | Type   | Description                                    |
|--------------|--------|------------------------------------------------|
| `status`     | string | Always `"success"` on success                  |
| `output`     | string | Absolute path where the output image was saved |
| `size_bytes` | int    | Size of the output image in bytes              |

### Error Response

**Status:** `400` (bad input) or `500` (processing error)

```json
{
  "error": "Description of what went wrong"
}
```

| Field   | Type   | Description       |
|---------|--------|-------------------|
| `error` | string | Error description |

### Common Errors

| Status | Error | Cause |
|--------|-------|-------|
| 400 | `No 'image' field in multipart form data.` | File upload missing the `image` field |
| 400 | `Invalid base64 data.` | The base64 string could not be decoded |
| 400 | `Failed to download image from URL: ...` | The URL was unreachable or returned an error |
| 400 | `JSON body must contain 'base64' or 'url' field.` | JSON provided but missing required field |
| 400 | `Unsupported content type.` | Neither multipart/form-data nor application/json |
| 500 | `No output image produced by workflow` | ComfyUI workflow completed but produced no output |

## GET /health

Health check endpoint.

```bash
curl http://localhost:3169/health
```

### Response

```json
{
  "status": "ok"
}
```
