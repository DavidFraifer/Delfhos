SHEETS_DOC = """
TOOL: sheets
DESCRIPTION: Read, write, format, and manage Google Sheets.
ACTIONS:
1. "READ": params:{range:"Sheet1!A1:C10"} → Returns 2D array.
2. "BATCH": params:{ops:["cmd1", "cmd2"]} → Executes SheetOps commands sequentially.

CRITICAL FORMAT RULES FOR 'ops' PARAMETER:
* ops MUST be an array of STRINGS only (never JSON objects like {'operation':'w'})
* Each element is a plain string command, e.g., 'w A1 | [values]' NOT {'operation':'w', 'range':'A1'}
* Format: ['@SheetName', 'command1', 'command2', ...] where each command is a string

SHEETOPS (inside 'ops' list - all elements are STRINGS):
* Context: @SheetName (REQUIRED first, creates if missing). Args separated by "|". Variables ($var) supported.

COMMANDS (all are plain strings):
[DATA] 
  - "w Range | Values" (write) - Example: "w A1 | ['Header1','Header2']"
  - "a | Values" (append) - Example: "a | ['Row1','Row2']"
  - "clr Range" (clear) - Example: "clr A1:C10"

[STRUCTURE]
  - "ins row|Idx|Qty" (insert rows) - Example: "ins row|5|2" (insert 2 rows at row 5)
  - "ins col|Idx|Qty" (insert columns) - Example: "ins col|3|1"
  - "del row|Idx|Qty" (delete rows) - Example: "del row|5|2"
  - "del col|Idx|Qty" (delete columns) - Example: "del col|3|1"
  - "mg Range" (merge cells) - Example: "mg A1:C1"
  - "auto Range" (auto-resize) - Example: "auto A:B"

[VISUALS]
  - "fmt Range | Tags" (format) - Tags: header,bold,italic,currency,percent,date,text:color,bg:color,border:side,alt-rows:color
    Colors: hex (#FF5733) or named (blue,red,green). Example: "fmt A1:B1 | header,bg:#87CEEB,text:#FFFFFF"
  - "chart Type | DataRange | DestCell" (chart) - Types: bar,line,pie,col
    Example: "chart bar | A1:B10 | A12"

[LOGIC]
  - "v Range | Rule" (validation) - Rules: "bool", "list:A,B,C", "date"
    Example: "v D1 | list:2023,2024"
  - "p Range | Type" (protection) - Types: strict, warning
    Example: "p A1:C10 | strict"

EXAMPLES (all ops are arrays of STRINGS):
- ["@Report", "clr A:Z", "w A1 | ['Item','Cost']", "a | ['Row1','Row2']", "fmt A1:B1 | header", "auto A:B"]
- ["@Dash", "chart line | Data!A1:B20 | A1", "v D1 | list:2023,2024"]
- ["@Sheet1", "w A1 | ['Name','Value']", "fmt A1:B1 | header,bg:#87CEEB,text:#FFFFFF"]

NEVER USE:
- {'operation':'w', 'range':'A1'} ❌
- [{'op':'w', 'args':['A1', ['Header']]}] ❌
- "A1:C1" (bare range without command) ❌

ALWAYS USE:
- ["@Sheet1", "w A1 | ['Header1','Header2']"] ✅
- ["@Sheet1", "a | ['Row1','Row2']"] ✅
""".strip()

