# MAPA API Contract

> Frontend (React/TypeScript) ↔ Backend (Python/FastAPI) shared interface specification.
>
> This document describes the endpoints and payloads currently implemented in [backend/app/api.py](/Users/yuanyu/Desktop/thesis/mapai_profiler_agent/backend/app/api.py:1).

---

## Base URL

| Environment | URL |
|---|---|
| Local dev | `http://localhost:8000` |

---

## Endpoints Overview

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/routes` | List available route fixtures |
| `GET` | `/api/zurich/data` | Fetch live Zurich OGD barriers, toilets, and parking near a point |
| `POST` | `/api/audio/transcribe` | Raw-audio speech transcription |
| `POST` | `/api/profile/turn` | Non-streaming profile turn |
| `POST` | `/api/profile/stream` | SSE streaming profile turn |
| `POST` | `/api/plan` | Non-streaming plan creation |
| `POST` | `/api/plan/stream` | SSE streaming plan creation |

---

## LLM Configuration

Every JSON `POST` request includes flattened LLM configuration fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `mode` | `"mock" \| "ollama"` | `"mock"` | Which LLM provider to use |
| `ollama_url` | `string` | `"http://localhost:11434"` | Ollama base URL |
| `ollama_model` | `string` | `"shmily_006/Qw3:4b_4bit"` | Ollama model tag used by the API request model |
| `ollama_timeout` | `number` | `300` | Ollama timeout in seconds |

---

## 1. `GET /api/health`

### Response

```json
{ "status": "ok" }
```

---

## 2. `GET /api/routes`

### Response — `RouteInfo[]`

```typescript
interface RouteInfo {
  route_id: string;
  name: string;
  step_free: boolean;
  total_distance_m: number;
  total_duration_min: number;
}
```

---

## 3. `GET /api/zurich/data`

### Query Parameters

| Name | Type | Default | Description |
|---|---|---|---|
| `lat` | `number` | `47.3782` | Query centre latitude (WGS-84) |
| `lon` | `number` | `8.5403` | Query centre longitude (WGS-84) |
| `radius_m` | `number` | `1000` | Search radius in metres |

### Response — `ZurichDataResponse`

```typescript
interface ZurichDataResponse {
  barriers: ZurichBarrierPoint[];
  toilets: ZurichToiletPoint[];
  parking: ZurichParkingPoint[];
  barriers_count: number;
  toilets_count: number;
  parking_count: number;
  fetch_errors: string[];
  center_lat: number;
  center_lon: number;
  radius_m: number;
}
```

---

## 4. `POST /api/audio/transcribe`

This endpoint accepts raw audio bytes in the request body. The backend reads the request body directly rather than expecting JSON or multipart form fields.

### Query Parameters

| Name | Type | Default | Description |
|---|---|---|---|
| `language` | `string` | `"en"` | Desired transcription language |

### Response — `AudioTranscriptionResponse`

```typescript
interface AudioTranscriptionResponse {
  transcript: string;
  language: string;
  provider: string;
  duration_sec?: number | null;
}
```

---

## 5. `POST /api/profile/turn`

### Request — `ProfileTurnRequest`

```typescript
interface ProfileTurnRequest {
  user_message: string;
  current_patch?: ProfilePatch | null;
  skipped_domains: string[];           // default: []
  question_context?: string | null;
  turn_count?: number;                 // default: 1
  language: string;                    // default: "en"
  consent_to_profile?: boolean;        // default: true
  mode: "mock" | "ollama";
  ollama_url: string;
  ollama_model: string;
  ollama_timeout?: number;
}
```

### Response — `ProfileTurnResponse`

```typescript
interface ProfileTurnResponse {
  profile_patch: ProfilePatch;
  confidence: ConfidenceScores;
  missing_critical_fields: string[];
  next_question: string | null;
  next_question_context: string | null;
  confirmation_text: string;
  speech_text: string;
}
```

---

## 6. `POST /api/plan`

### Request — `PlanRequest`

```typescript
interface PlanRequest {
  profile_patch: ProfilePatch;
  route_id: string;                     // default: "route_with_stairs"
  language: string;                     // default: "en"
  image_hazards?: ImageHazardsSummary | null;
  mode: "mock" | "ollama";
  ollama_url: string;
  ollama_model: string;
  ollama_timeout?: number;
}
```

### Response — `PlanResponse`

```typescript
interface PlanResponse {
  summary: string;
  directions: string[];
  alerts: string[];
  checklist: string[];
  if_you_get_lost: string[];
  preferences_applied: string[];
  speech_text: string;
}
```

---

## 7. SSE Stream Endpoints

`POST /api/profile/stream` and `POST /api/plan/stream` accept the same request bodies as their non-streaming counterparts but return **Server-Sent Events** (`text/event-stream`).

### Event Types

```typescript
{ "type": "progress", "agent": "<name>", "status": "starting" }
{ "type": "progress", "agent": "<name>", "status": "done", "duration_ms": 123 }
{ "type": "result", ...responseFields, "agent_reply": "...", "trace_steps": [...] }
{ "type": "error", "message": "<error message>" }
```

For `profile/stream`, `responseFields` match `ProfileTurnResponse`.
For `plan/stream`, `responseFields` match `PlanResponse`.

---

## Domain Models

### `ProfilePatch`

```typescript
interface ProfilePatch {
  needs?: {
    vision?: {
      blind_or_low_vision?: boolean | null;
      prefers_landmarks?: boolean | null;
    };
    hearing?: {
      deaf_or_hard_of_hearing?: boolean | null;
      sign_language_user?: boolean | null;
    };
    mobility?: {
      wheelchair_user?: boolean | null;
      needs_step_free_route?: boolean | null;
      avoid_long_walks?: boolean | null;
    };
    cognitive?: {
      needs_simple_language?: boolean | null;
      needs_memory_support?: boolean | null;
      reading_or_memory_difficulty_or_child?: boolean | null;
    };
  };
  communication?: {
    output_mode?: "standard_text" | "simple_text" | "sign_gloss_text";
  };
  preferences?: {
    avoid_crowds?: boolean | null;
    extra_time_buffer_min?: number | null;
  };
}
```

### `ConfidenceScores`

```typescript
interface ConfidenceScores {
  overall: number;
  per_domain: {
    vision: number;
    hearing: number;
    mobility: number;
    cognitive: number;
  };
}
```

### `ImageHazardsSummary`

```typescript
type RiskLevel = "none" | "low" | "medium" | "high";

interface ImageHazardsSummary {
  stairs?: RiskLevel;
  slope?: RiskLevel;
  crowd?: RiskLevel;
  scene_summary?: string | null;
  visible_objects?: string[];
  accessibility_cues?: string[];
}
```

### `ZurichBarrierPoint`

```typescript
interface ZurichBarrierPoint {
  lat: number;
  lon: number;
  category: string;
  severity: number;          // 1–5
  severity_label: string;
  tags: string;
  quartier: string;
  temporary: boolean;
  distance_m: number;
}
```

### `ZurichToiletPoint`

```typescript
interface ZurichToiletPoint {
  lat: number;
  lon: number;
  name: string;
  address: string;
  category: string;
  wheelchair_accessible: boolean;
  opening_hours: string;
  free: boolean;
  distance_m: number;
}
```

### `ZurichParkingPoint`

```typescript
interface ZurichParkingPoint {
  lat: number;
  lon: number;
  address: string;
  type: string;
  fee_required: boolean;
  distance_m: number;
}
```

---

## Code References

| Layer | File | Purpose |
|---|---|---|
| Frontend | `frontend/src/lib/api-contract.ts` | TypeScript contract definitions |
| Frontend | `frontend/src/lib/backend-api.ts` | API client and schema translation |
| Backend | `backend/app/contract.py` | Python contract definitions |
| Backend | `backend/app/api.py` | FastAPI endpoint implementations |
| Backend | `backend/app/models.py` | Core Pydantic models |
