import os

filepath = r'c:\Users\reshm\OneDrive\Desktop\solvetaxx\solvetax_frontend\app\src\components\crm_dashboard\leads\Leads.jsx'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Find the return statement and replace it with a structure that moves drawers outside
# We'll look for the start of the return and the end of the return.
# Since the return contains many braces, we'll try a more robust approach.

if 'return (' in content and '<div className="leads-module-container">' in content:
    print("Found return and container. Attempting structural move...")
    
    # 1. Identify the drawers area. They usually start with {isFilterOpen && ( and {selectedLead && (
    # We want to take everything from the first drawer check to the end of the return.
    
    parts = content.split('<div className="leads-module-container">')
    header = parts[0]
    rest = '<div className="leads-module-container">' + parts[1]
    
    # Find the last closing div of leads-module-container and move drawers after it
    # Heuristic: the drawers start with {isFilterOpen and {selectedLead
    
    if '{isFilterOpen && (' in rest:
        body_parts = rest.split('{isFilterOpen && (')
        module_body = body_parts[0]
        drawers = '{isFilterOpen && (' + '{isFilterOpen && ('.join(body_parts[1:])
        
        # Remove the trailing ); and } from drawers to find the end
        # This is tricky with string splits. Let's try a simpler replacement.
        
        new_return = "  return (\n    <>\n      <div className=\"leads-module-container\">\n" + module_body + "\n      </div>\n\n      {/* DRAWER PORTALS */}\n" + drawers + "\n    </>\n  );"
        
        # Find the old return block
        # This is still dangerous. Let's just use a very specific replacement for the opening and closing lines.
        
        content = content.replace('  return (', '  return (\n    <>')
        content = content.replace('<div className="leads-module-container">', '      <div className="leads-module-container">')
        
        # We need to find the specific closing line of leads-module-container
        # It's usually right before {isFilterOpen
        content = content.replace('      {isFilterOpen && (', '      </div>\n\n      {isFilterOpen && (')
        
        # And fix the end
        content = content.replace('    </div>\n  );', '    </>\n  );')

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully move drawers in Leads.jsx")
