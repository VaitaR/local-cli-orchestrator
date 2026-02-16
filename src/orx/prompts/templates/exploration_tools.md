## Exploration Tools

Do NOT guess file paths. Do NOT read huge files just to find one function. Use these CLI tools to explore the codebase efficiently:

### Find files by name
```bash
fd -t f "pattern"            # Find files matching pattern
fd -e py "config"            # Find .py files with "config" in name
fd -e yaml -e json .         # List all YAML and JSON files
```

### Search code (ripgrep)
```bash
rg -n "function_name" src/   # Search with line numbers
rg -n -C 2 "class Foo" .    # Search with 2 lines of context
rg -l "import X"             # List files containing pattern (names only)
rg -t py "def connect"       # Search only in Python files
```

### Inspect / edit JSON safely
```bash
jq '.key' file.json          # Read a specific key
jq '.scripts.test' package.json
```

### Understand project structure
```bash
tree -L 2 -I '__pycache__|node_modules|.git'   # Directory tree (depth 2)
```

### Example Workflow
1. `fd "auth"` → found `src/auth/service.py`
2. `rg -n "class AuthService" src/auth/service.py` → found at line 15
3. Read `src/auth/service.py` starting at line 15

**Rule**: Always search before reading. This saves tokens and finds the right code faster.
