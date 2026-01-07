import os
import pandas as pd
import re
import sys

def parse_fortigate_log_line(line):
    if not line.strip():
        return None
    
    fields = ['date', 'time', 'eventtime', 'tz', 'logid', 'type', 'subtype', 'level', 'vd', 'logdesc', 
              'sn', 'user', 'ui', 'method', 'srcip', 'dstip', 'action', 'status', 'reason', 'msg']
    data = {field: '' for field in fields}
    
    remaining = line
    for field in fields[:-1]:  # All except 'msg'
        # Match field="value" or field=value (quoted or unquoted)
        match = re.search(rf'{field}=(?:"(.*?)"|([^\s"]+))\s', remaining)
        if match:
            value = match.group(1) if match.group(1) is not None else match.group(2)
            data[field] = value or ''
            remaining = remaining[match.end():].lstrip()
    
    # Extract msg – it's always the last quoted field
    msg_match = re.search(r'msg="(.*?)"(?:\s*$|\s+\w+=)', line + ' ')
    if msg_match:
        data['msg'] = msg_match.group(1).replace('""', '"')  # Unescape double quotes
    
    return data

def convert_file(input_path, output_path):
    print(f"Processing: {os.path.basename(input_path)}")
    
    parsed_lines = []
    with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line_num, line in enumerate(f, 1):
            try:
                parsed = parse_fortigate_log_line(line.strip())
                if parsed:
                    parsed_lines.append(parsed)
            except Exception as e:
                print(f"  Warning: Could not parse line {line_num}: {e}")
    
    if not parsed_lines:
        print("  No valid log entries found.")
        return
    
    df = pd.DataFrame(parsed_lines)
    df.to_csv(output_path, index=False)
    print(f"  → CSV created: {os.path.basename(output_path)} ({len(df)} rows)\n")

def main(input_arg):
    input_arg = input_arg.strip('"\'')  # Remove surrounding quotes if any
    
    if os.path.isfile(input_arg):
        # Single file – accept .log or .txt
        if not input_arg.lower().endswith(('.log', '.txt')):
            print("Please provide a .log or .txt file.")
            return
        output_path = os.path.splitext(input_arg)[0] + '.csv'
        convert_file(input_arg, output_path)
    
    elif os.path.isdir(input_arg):
        # Process all .log and .txt files in the folder
        log_files = [f for f in os.listdir(input_arg) 
                     if f.lower().endswith(('.log', '.txt'))]
        if not log_files:
            print("No .log or .txt files found in the directory.")
            return
        
        print(f"Found {len(log_files)} log file(s) to convert:\n")
        for log_file in sorted(log_files):
            input_path = os.path.join(input_arg, log_file)
            output_path = os.path.join(input_arg, os.path.splitext(log_file)[0] + '.csv')
            convert_file(input_path, output_path)
    
    else:
        print("Error: The path is not a valid file or folder.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("FortiGate Log to CSV Converter")
        print("Usage:")
        print("  python fortigate_log_to_csv.py \"path\\to\\your_log_file.log\"")
        print("  python fortigate_log_to_csv.py \"path\\to\\your_logs_folder\"")
        print("\nExamples:")
        print("  python fortigate_log_to_csv.py \"C:\\Users\\YourName\\Downloads\\mylog.log\"")
        print("  python fortigate_log_to_csv.py \"C:\\Logs\"")
    else:
        main(sys.argv[1])