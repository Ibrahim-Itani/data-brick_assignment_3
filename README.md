# Weather MCP Server - DataExpert Bootcamp Assignment 3

A Model Context Protocol (MCP) server that provides weather data and intelligent travel recommendations through the Databricks AI platform. This server integrates real-time weather data from Open-Meteo and exposes tools the Databricks Assistant can call via the MCP protocol.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Databricks AI Platform                      │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              Databricks Assistant (Genie)                 │  │
│  │              (MCP Client)                                 │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            │                                     │
│                            │ MCP Protocol (SSE/HTTP)             │
│                            │                                     │
│  ┌─────────────────────────▼─────────────────────────────────┐  │
│  │          Weather MCP Server (FastMCP)                     │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │  MCP Tools:                                         │  │  │
│  │  │  • get_current_weather(location)                    │  │  │
│  │  │  • get_forecast(location, days)                     │  │  │
│  │  │  • get_travel_recommendation(location, date)        │  │  │
│  │  │  • vector_search(query, limit)                      │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │               │                            │                │  │
│  └───────────────┼────────────────────────────┼────────────────┘  │
│                  │                            │                   │
│     ┌────────────▼────────────┐   ┌──────────▼────────────────┐  │
│     │   weather_broker.py     │   │   Lakebase Postgres       │  │
│     │   (Weather API Logic)   │   │   (pgvector)              │  │
│     └────────────┬────────────┘   │                           │  │
│                  │                │  • weather_documents       │  │
│                  │                │  • weather_documents_      │  │
│                  │                │    embeddings (384-dim)    │  │
│                  │                │  • mcp_tool_traces         │  │
│                  │                │    (observability)         │  │
│                  │                └───────────────────────────┘  │
└──────────────────┼──────────────────────────────────────────────┘
                   │
                   │ HTTPS
                   │
         ┌─────────▼──────────┐
         │   Open-Meteo API   │
         │   (Free, No Auth)  │
         │                    │
         │ • Geocoding        │
         │ • Current Weather  │
         │ • 16-day Forecast  │
         └────────────────────┘
```

## MCP Tools

The server exposes four tools through the Model Context Protocol:

### 1. `get_current_weather(location: str)`
Retrieves current weather conditions for a specified location.

**Parameters:**
- `location` (str): City name and state (e.g., "San Francisco, CA")

**Returns:**
- `temperature_f`: Current temperature in Fahrenheit
- `conditions`: Weather description (e.g., "Clear sky", "Moderate rain")
- `humidity_percent`: Relative humidity percentage
- `wind_speed_mph`: Wind speed in miles per hour
- `timestamp`: ISO 8601 timestamp of the observation

**Example:**
```json
{
  "location": "San Francisco",
  "temperature_f": 62.5,
  "conditions": "Partly cloudy",
  "humidity_percent": 75,
  "wind_speed_mph": 12.3,
  "timestamp": "2026-08-10T15:30:00"
}
```

### 2. `get_forecast(location: str, days: float)`
Provides multi-day weather forecast (up to 16 days).

**Parameters:**
- `location` (str): City name and state
- `days` (float): Number of days to forecast (1-16)

**Returns:**
- `forecast_days`: Array of daily forecasts with:
  - `date`: Forecast date (YYYY-MM-DD)
  - `temp_high_f`: High temperature in Fahrenheit
  - `temp_low_f`: Low temperature in Fahrenheit
  - `precipitation_probability_percent`: Chance of precipitation
  - `conditions`: Weather description

**Example:**
```json
{
  "location": "Boston",
  "forecast_days": [
    {
      "date": "2026-08-11",
      "temp_high_f": 78,
      "temp_low_f": 62,
      "precipitation_probability_percent": 30,
      "conditions": "Partly cloudy"
    }
  ]
}
```

### 3. `get_travel_recommendation(location: str, date: str)`
Provides intelligent travel recommendations based on weather forecast.

**Parameters:**
- `location` (str): Destination city and state
- `date` (str): Travel date in YYYY-MM-DD format

**Returns:**
- `overall_assessment`: Summary assessment (e.g., "Excellent travel conditions")
- `weather_summary`: Conditions, temperatures, precipitation probability
- `recommendations`: Array of specific travel advice
- `items_to_bring`: List of recommended items (umbrella, jacket, sunscreen, etc.)

**Reasoning Logic:**
- Precipitation > 60%: Suggests rescheduling outdoor activities
- Precipitation 40-60%: Recommends rain gear
- Temperature > 85°F: Advises hydration and sun protection
- Temperature < 40°F: Suggests warm layers
- Large temp swings (>25°F): Recommends layering

**Example:**
```json
{
  "location": "Seattle",
  "date": "2026-08-15",
  "overall_assessment": "Good travel conditions with minor considerations",
  "weather_summary": {
    "conditions": "Light rain",
    "high_temp_f": 68,
    "low_temp_f": 55,
    "precipitation_probability_percent": 45
  },
  "recommendations": [
    "Moderate chance of rain - be prepared for wet weather",
    "Cool weather - bring a jacket or sweater"
  ],
  "items_to_bring": ["umbrella", "jacket"]
}
```

### 4. `vector_search(query: str, limit: int)`
Performs semantic search over historical weather documents using pgvector.

**Parameters:**
- `query` (str): Natural language search query (e.g., "severe storm warnings")
- `limit` (int): Maximum results to return (default: 10)

**Returns:**
- `query`: The search query
- `documents`: Array of matching documents with:
  - `id`, `location`, `headline`, `narrative_text`
  - `source_type`, `published_utc`, `issued_at`
  - `payload`: JSONB with additional metadata
  - `similarity`: Cosine similarity score (0-1)
- `model`: Embedding model used (sentence-transformers/all-MiniLM-L6-v2)

**Implementation:**
- Uses 384-dimensional sentence embeddings
- Leverages pgvector's cosine similarity operator (`<=>`)
- Joins embeddings table with weather documents table

## Weather API

### Open-Meteo API
This server uses the **Open-Meteo API** for weather data:

- **Website:** https://open-meteo.com/
- **Authentication:** None required (free, open-source weather API)
- **Rate Limits:** Generous free tier, no API key needed
- **Endpoints Used:**
  - Geocoding API: Converts city names to coordinates
  - Forecast API: Current conditions and 16-day forecasts
- **Data Format:** JSON responses with WMO weather codes
- **Coverage:** Global weather data

**Why Open-Meteo?**
- No authentication simplifies deployment
- High-quality data from multiple sources (NOAA, DWD, MeteoFrance)
- Well-documented REST API
- Reliable uptime and performance

## Setup Instructions

### Prerequisites
- Databricks workspace with serverless compute
- Lakebase Postgres instance (for vector search)
- Python 3.9+

### 1. Clone the Repository
```bash
git clone <repository-url>
cd databricks_assignment_3
```

### 2. Set Up Lakebase Tables

Create the weather documents table:
```sql
CREATE TABLE production.weather_documents (
    id TEXT PRIMARY KEY,
    location TEXT NOT NULL,
    source_type TEXT NOT NULL,
    headline TEXT NOT NULL,
    narrative_text TEXT NOT NULL,
    issued_at TIMESTAMP WITH TIME ZONE,
    payload JSONB NOT NULL,
    synced_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);
```

Create the embeddings table with pgvector:
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE production.weather_documents_embeddings (
    id TEXT PRIMARY KEY,
    location TEXT NOT NULL,
    headline TEXT NOT NULL,
    published_utc TIMESTAMP WITH TIME ZONE,
    embedding VECTOR(384) NOT NULL,
    model_name TEXT NOT NULL,
    embedded_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

CREATE INDEX ON production.weather_documents_embeddings 
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

Create the MCP tool tracing table:
```sql
CREATE TABLE production.mcp_tool_traces (
    trace_id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    user_email TEXT NOT NULL,
    parameters JSONB NOT NULL,
    result JSONB,
    duration_ms FLOAT NOT NULL,
    error TEXT,
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
);

-- Indexes for common query patterns
CREATE INDEX idx_traces_session ON production.mcp_tool_traces(session_id);
CREATE INDEX idx_traces_tool ON production.mcp_tool_traces(tool_name);
CREATE INDEX idx_traces_user ON production.mcp_tool_traces(user_email);
CREATE INDEX idx_traces_timestamp ON production.mcp_tool_traces(timestamp DESC);
```

### 3. Configure app.yaml (Databricks App configuration)

Create an `app.yaml` file in the `mcp_server/` directory. The repository already includes `mcp_server/app.yaml`; it contains the command, resources, and environment variable names used when deploying the Databricks App. The values in the repository's `mcp_server/app.yaml` are:

```yaml
command:
  - "python"
  - "weather_mcp_server.py"

resources:
  - name: requirements
    source:
      path: ./requirements.txt

env:
  - name: LAKEBASE_SECRET_SCOPE
    value: "database"
  - name: LAKEBASE_SECRET_KEY
    value: "lakebase-url"
  - name: WEATHER_TABLE_NAME
    value: "weather_documents"
  - name: EMBEDDINGS_TABLE_NAME
    value: "weather_documents_embeddings"
  - name: TRACING_TABLE_NAME
    value: "mcp_tool_traces"
```

Note: the `app.yaml` in the repository uses simple table names (no `production.` schema prefix) and expects a single secret key name (`LAKEBASE_SECRET_KEY`) stored in the scope named by `LAKEBASE_SECRET_SCOPE`. If you prefer schema-qualified table names or additional env vars (for example, an embedding model name), add them to `mcp_server/app.yaml` before deploying.

### 4. Set Up Databricks Secrets (for Lakebase)

```python
# Run setup_secrets.py to configure Lakebase connection
from databricks.sdk import WorkspaceClient
import base64

w = WorkspaceClient()

# Create secret scope
w.secrets.create_scope(scope="database")

# Add Lakebase credentials
w.secrets.put_secret(
    scope="database",
    key="LAKEBASE_HOST",
    string_value=base64.b64encode(b"your-host.cloud.databricks.com").decode()
)
w.secrets.put_secret(
    scope="database",
    key="LAKEBASE_DATABASE",
    string_value=base64.b64encode(b"new_database").decode()
)
w.secrets.put_secret(
    scope="database",
    key="LAKEBASE_HTTP_PATH",
    string_value=base64.b64encode(b"/sql/1.0/endpoints/...").decode()
)
```

(When deploying via Databricks Apps you can also place a single Lakebase connection URL in the secret referenced by `LAKEBASE_SECRET_KEY` if your deployment prefers a single secret.)

### 5. Install Dependencies

The `requirements.txt` includes:
```
databricks-sdk>=0.30.0
psycopg2-binary>=2.9.9
sqlalchemy>=2.0.30
fastmcp>=3.2.0
python-dotenv>=1.0.1
requests>=2.31.0
sentence-transformers>=2.2.0
```

### 6. Deploy as Databricks App

```bash
cd mcp_server
databricks apps create weather-mcp
databricks apps deploy weather-mcp --source-code-path .
```

### 7. Register MCP Server in Databricks

1. Navigate to the Databricks AI workspace
2. Go to **Settings** → **MCP Servers**
3. Click **Add MCP Server**
4. Enter:
   - Name: `Weather MCP Server`
   - URL: `https://<workspace>.cloud.databricks.com/apps/weather-mcp`
   - Transport: `HTTP (SSE)`
5. Save and test the connection

### 8. Test the Tools

In Databricks Assistant:
```
What's the current weather in San Francisco?

Get me a 5-day forecast for Boston.

Should I travel to Seattle on August 15th? What should I bring?

Search for severe storm warnings in the past week.
```

## Project Structure

```
databricks_assignment_3/
├── mcp_server/
│   ├── weather_mcp_server.py    # FastMCP server with tool definitions
│   ├── weather_broker.py        # Weather API logic (Open-Meteo)
│   ├── lakebase.py              # Postgres connection and queries
│   ├── requirements.txt         # Python dependencies
│   └── app.yaml                 # Databricks App configuration
├── setup_secrets.py             # Script to configure secrets
├── README.md                    # This file
├── LICENSE
└── .gitignore
```

## Key Features

- **Real-time Weather Data**: Current conditions and forecasts via Open-Meteo
- **Intelligent Recommendations**: Context-aware travel advice based on multiple weather factors
- **Semantic Search**: Vector-based search over historical weather documents
- **Full Tracing & Observability**: Automatic logging of all MCP tool invocations with session tracking
- **Scalable Architecture**: Built on Databricks Apps with serverless compute
- **No Authentication Required**: Open-Meteo API needs no API key
- **FastMCP Framework**: Easy-to-extend tool definitions
- **pgvector Integration**: Efficient similarity search with 384-dimensional embeddings

## Development

### Local Testing

```bash
# Set environment variables
export WEATHER_TABLE_NAME="production.weather_documents"
export EMBEDDINGS_TABLE_NAME="production.weather_documents_embeddings"
export LAKEBASE_SECRET_SCOPE="database"

# Run the server locally
cd mcp_server
python weather_mcp_server.py
```

The server will start on `http://0.0.0.0:8000` by default.

### Adding New Tools

1. Add function to `weather_broker.py`
2. Decorate with `@mcp.tool` and `@trace_tool` in `weather_mcp_server.py`
3. Add docstring with clear parameter and return descriptions
4. Redeploy the app

### MCP Tracing & Observability

The server automatically traces all MCP tool invocations to a Lakebase Postgres table. Each trace captures:

- **Session ID**: Unique UUID generated per agent conversation session
- **Tool Name**: Which MCP tool was invoked
- **User Email**: Who called the tool (from Databricks headers)
- **Parameters**: JSON of input parameters
- **Result**: JSON of the tool's output
- **Duration**: Execution time in milliseconds
- **Error**: Error message if the tool failed
- **Timestamp**: When the call occurred

#### Querying Traces

**View recent tool usage:**
```sql
SELECT 
    timestamp,
    tool_name,
    user_email,
    duration_ms,
    parameters->>'location' as location
FROM production.mcp_tool_traces
ORDER BY timestamp DESC
LIMIT 50;
```

**Analyze session activity:**
```sql
SELECT 
    session_id,
    user_email,
    COUNT(*) as tool_calls,
    AVG(duration_ms) as avg_duration_ms,
    MIN(timestamp) as session_start,
    MAX(timestamp) as session_end
FROM production.mcp_tool_traces
GROUP BY session_id, user_email
ORDER BY session_start DESC;
```

**Most popular tools:**
```sql
SELECT 
    tool_name,
    COUNT(*) as call_count,
    AVG(duration_ms) as avg_duration,
    COUNT(CASE WHEN error IS NOT NULL THEN 1 END) as error_count
FROM production.mcp_tool_traces
WHERE timestamp > NOW() - INTERVAL '7 days'
GROUP BY tool_name
ORDER BY call_count DESC;
```

**Tool performance by user:**
```sql
SELECT 
    user_email,
    tool_name,
    COUNT(*) as calls,
    AVG(duration_ms) as avg_ms,
    MAX(duration_ms) as max_ms
FROM production.mcp_tool_traces
WHERE timestamp > NOW() - INTERVAL '24 hours'
GROUP BY user_email, tool_name
ORDER BY user_email, calls DESC;
```

**Error analysis:**
```sql
SELECT 
    tool_name,
    error,
    parameters,
    COUNT(*) as occurrences,
    MAX(timestamp) as last_occurred
FROM production.mcp_tool_traces
WHERE error IS NOT NULL
GROUP BY tool_name, error, parameters
ORDER BY occurrences DESC, last_occurred DESC;
```

#### Session ID Generation

Session IDs are automatically generated using UUID4 when:
- A new HTTP request arrives at the MCP server
- No existing session ID is found in the context

The session ID persists across multiple tool calls within the same conversation, enabling you to:
- Track complete user journeys
- Understand tool usage patterns
- Debug multi-step workflows
- Calculate session-level metrics

#### Logs Proof:

The user is asking for a travel recommendation for a specific date, so I will use the get_travel_recommendation function to provide a suggestion.

Tool call: get_travel_recommendation
<tool_call>{"id":"fNqkwXZGdqVKYuvmqzls","name":"get_travel_recommendation","arguments":"{\"location\":\"New York, NY\",\"date\":\"2026-09-03\"}"}</tool_call>



Tool call output:
<tool_call_result>{"id":"fNqkwXZGdqVKYuvmqzls","content":"{\"error\":\"Forecast only available up to 16 days in advance\"}"}</tool_call_result>

The travel recommendation function is unable to provide a suggestion for September 3rd as it is beyond the 16-day forecast limit.

However, I can suggest some general ideas for travel destinations in early September. Since the weather is usually mild and pleasant during this time, you might consider visiting places with outdoor attractions, such as national parks, beaches, or cities with a rich history and culture.

Some popular destinations in the United States during early September include:

* New York City, with its many museums, landmarks, and cultural events
* The beach towns of California, such as Santa Monica or San Diego
* The scenic cities of the Pacific Northwest, such as Portland or Seattle
* The historic cities of the East Coast, such as Boston or Philadelphia

Keep in mind that these are just general suggestions, and the best destination for you will depend on your personal preferences and interests. If you have any specific ideas or preferences, I'd be happy to try and help you further!

#### Screenshot:
<img width="436" height="425" alt="Screenshot 2026-08-10 at 3 49 51 pm" src="https://github.com/user-attachments/assets/aa7b5a5c-ed8c-457f-a666-d305c4d50d1c" />
<img width="853" height="863" alt="Screenshot 2026-08-10 at 3 50 06 pm" src="https://github.com/user-attachments/assets/23912045-6bed-4a67-ba63-828fdf2b8dc4" />
<img width="841" height="759" alt="Screenshot 2026-08-10 at 3 49 42 pm" src="https://github.com/user-attachments/assets/a7cf02c2-6189-4153-b7e4-bea49c74804a" />

#### Disabling Tracing

To disable tracing (e.g., for performance testing):
1. Remove the `@trace_tool` decorator from tool functions
2. Or comment out the `_log_trace()` call in the decorator

## License

See LICENSE file for details.

## Credits

- Weather data provided by [Open-Meteo](https://open-meteo.com/)
- Built for the DataExpert Bootcamp - Assignment 3
- MCP Framework: [FastMCP](https://github.com/jlowin/fastmcp)
- Vector embeddings: [sentence-transformers](https://www.sbert.net/)
