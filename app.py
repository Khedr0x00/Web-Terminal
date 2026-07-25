# Filename: terminal.py
# Description: A Flask application with SocketIO to run a
# multi-user, interactive terminal. This version has been updated
# to support multiple configurable paths for 'commands' and 'notes'.
#
import os
import subprocess
import threading
import sys
import time
import json 
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

# Attempt to import pty and tty, which are Unix-specific
try:
    import pty
    import tty
    UNIX_SYSTEM = True
except ImportError:
    UNIX_SYSTEM = False
    print("Warning: pty and tty modules not found. Assuming Windows system.")

# Flask and SocketIO initialization
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a_very_secret_key_for_terminal'
socketio = SocketIO(app)

# --- Global State for Multiple Sessions ---
# Dictionary to store each client's terminal session.
sessions = {}

@app.route('/')
def index():
    """Renders the single-page HTML for the web terminal."""
    return render_template('index.html')

# --- Utility Functions for File Management and Path Configuration ---
PATHS_FILE = "paths.json" 

# NEW: Default paths are now arrays
DEFAULT_PATHS = {
    "commands_paths": ["commands"],
    "notes_paths": ["notes"]
}

def load_paths():
    """Loads COMMANDS_PATHS and NOTES_PATHS from paths.json, or uses defaults."""
    if os.path.exists(PATHS_FILE):
        try:
            with open(PATHS_FILE, 'r') as f:
                data = json.load(f)
                # Load paths, ensuring they are lists and fall back to default if keys are missing
                commands = data.get("commands_paths", DEFAULT_PATHS["commands_paths"])
                notes = data.get("notes_paths", DEFAULT_PATHS["notes_paths"])
                
                # Ensure all paths are strings, non-empty, and unique
                commands = list(set([str(p).strip() for p in commands if isinstance(p, str) and p.strip()]))
                notes = list(set([str(p).strip() for p in notes if isinstance(p, str) and p.strip()]))

                # Ensure at least one path exists for each type
                return commands if commands else DEFAULT_PATHS["commands_paths"], \
                       notes if notes else DEFAULT_PATHS["notes_paths"]
                       
        except Exception as e:
            print(f"Error loading paths from {PATHS_FILE}: {e}. Using default paths.")
    return DEFAULT_PATHS["commands_paths"], DEFAULT_PATHS["notes_paths"]

def save_paths(commands_paths, notes_paths):
    """Saves the current paths to paths.json."""
    try:
        with open(PATHS_FILE, 'w') as f:
            json.dump({
                "commands_paths": commands_paths,
                "notes_paths": notes_paths
            }, f, indent=4)
        print(f"Paths saved to {PATHS_FILE}.")
    except Exception as e:
        print(f"Error saving paths to {PATHS_FILE}: {e}")

# Initialize paths from file or use defaults (now arrays)
COMMANDS_PATHS, NOTES_PATHS = load_paths() 

def create_dummy_files():
    """Creates initial dummy files for demonstration purposes in the FIRST path of each list."""
    global COMMANDS_PATHS, NOTES_PATHS
    
    # Use the first path in the list for dummy creation
    commands_dir = COMMANDS_PATHS[0]
    notes_dir = NOTES_PATHS[0]

    # Create some example command files for demonstration
    with open(os.path.join(commands_dir, "ls_command.sh"), "w") as f:
        f.write("echo 'Listing files in the current directory:'\nls\n")
    with open(os.path.join(commands_dir, "greet.sh"), "w") as f:
        f.write("echo 'Hello, World!'\n")
    with open(os.path.join(commands_dir, "system_info.sh"), "w") as f:
        f.write("echo 'Fetching system information...'\n")
        if UNIX_SYSTEM:
            f.write("uname -a\n")
        else:
            f.write("systeminfo\n")

    # Create some example note files for demonstration
    with open(os.path.join(notes_dir, "database_schema.txt"), "w") as f:
        f.write("User table: id, username, email\nProducts table: id, name, price, stock")
    with open(os.path.join(notes_dir, "important_queries.txt"), "w") as f:
        f.write("SELECT * FROM users WHERE active = true;\nUPDATE products SET stock = 0 WHERE id = 10;")
    with open(os.path.join(notes_dir, "backup_plan.txt"), "w") as f:
        f.write("1. Stop the database service.\n2. Create a compressed backup of the data directory.\n3. Restart the service.")

def setup_directories():
    """Ensures all necessary directories exist and creates dummy files only if the default directory hasn't been initialized."""
    global COMMANDS_PATHS, NOTES_PATHS
    
    # Check if a sentinel file exists in the *default* path to decide if we need dummy files
    SENTINEL_FILE = os.path.join(DEFAULT_PATHS["commands_paths"][0], ".initialized")
    create_dummies = not os.path.exists(SENTINEL_FILE)
    
    all_paths = COMMANDS_PATHS + NOTES_PATHS
    
    for directory in all_paths:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"Created directory: {directory}")

    # If the default directory has never been initialized, run the dummy creation logic
    if create_dummies:
        # Ensure the first default directory exists before creating the sentinel file
        if not os.path.exists(DEFAULT_PATHS["commands_paths"][0]):
            os.makedirs(DEFAULT_PATHS["commands_paths"][0])

        create_dummy_files()
        try:
            # Create the sentinel file in the *default* directory
            with open(SENTINEL_FILE, 'w') as f:
                f.write(f"Initialized at {time.ctime()}")
            print("Created initial dummy files.")
        except Exception as e:
            print(f"Warning: Could not create sentinel file {SENTINEL_FILE}: {e}")

    print(f"Commands paths: {COMMANDS_PATHS}")
    print(f"Notes paths: {NOTES_PATHS}")


# ... (read_from_pty, read_from_process, handle_connect, handle_input, handle_disconnect remain unchanged) ...
def read_from_pty(sid, master_fd):
    """
    Continuously reads data from a specific PTY and sends it to the
    correct client via WebSockets.
    """
    while True:
        try:
            data = os.read(master_fd, 1024)
            if data:
                socketio.emit('terminal_output', {'data': data.decode('utf-8', errors='ignore')}, room=sid)
            else:
                break
        except OSError:
            break
        except Exception as e:
            print(f"Error in read_from_pty for {sid}: {e}")
            break

def read_from_process(sid, process):
    """
    Continuously reads data from a specific subprocess's stdout/stderr
    and sends it to the correct client via WebSockets.
    This version reads character-by-character for non-blocking behavior on Windows.
    """
    while process.poll() is None:
        try:
            # Read one byte at a time for real-time streaming
            char = process.stdout.read(1)
            if char:
                # Decode the byte and emit to the client
                socketio.emit('terminal_output', {'data': char.decode('utf-8', errors='ignore')}, room=sid)
            else:
                # Add a small delay if no data is available to prevent
                # the thread from consuming too much CPU.
                time.sleep(0.01)
        except Exception as e:
            # This can happen if the process closes
            print(f"Error in read_from_process for {sid}: {e}")
            break

@socketio.on('connect')
def handle_connect():
    """
    Spawns a new shell process for each connecting client (i.e., each new tab).
    """
    sid = request.sid
    # ... (connection logic remains the same) ...
    if sid in sessions and sessions[sid].get('process') and sessions[sid]['process'].poll() is None:
        print(f"Client {sid} reconnected. Using existing terminal process.")
        emit('terminal_output', {'data': '\r\nReconnected to your existing terminal session.\r\n'}, room=sid)
        return
        
    print(f'Client {sid} connected. Starting new terminal process.')
    
    if UNIX_SYSTEM:
        master_fd, slave_fd = pty.openpty()
        shell_process = subprocess.Popen(
            ['/bin/bash'],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            preexec_fn=os.setsid,
            universal_newlines=True,
            env=dict(os.environ, PYTHONUNBUFFERED='1')
        )
        
        # Store the new session data
        sessions[sid] = {
            'master_fd': master_fd,
            'slave_fd': slave_fd,
            'process': shell_process,
            'reader_thread': threading.Thread(target=read_from_pty, args=(sid, master_fd))
        }
    else: # Windows system
        shell_process = subprocess.Popen(
            ['cmd.exe'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=False,
            bufsize=0,
            env=dict(os.environ, PYTHONUNBUFFERED='1')
        )
        
        # Store the new session data, including a buffer for accumulating commands
        sessions[sid] = {
            'process': shell_process,
            'reader_thread': threading.Thread(target=read_from_process, args=(sid, shell_process)),
            'buffer': '',
            'has_set_encoding': False,
            'in_interactive_mode': False,
            'interactive_process': None,
            'interactive_reader_thread': None
        }
    
    # Start the reader thread for the new session
    sessions[sid]['reader_thread'].daemon = True
    sessions[sid]['reader_thread'].start()

@socketio.on('terminal_input')
def handle_input(data):
    """
    Writes client keyboard input to their specific shell process.
    """
    sid = request.sid
    session = sessions.get(sid)
    # ... (function body remains unchanged) ...
    if not session:
        print(f"Session not found for {sid}")
        return

    command_char = data.get('command')
    if not command_char:
        return

    if UNIX_SYSTEM:
        master_fd = session.get('master_fd')
        if master_fd:
            try:
                os.write(master_fd, command_char.encode('utf-8'))
            except OSError:
                print(f"Error writing to PTY for {sid}. Disconnecting session.")
                del sessions[sid]
    else: # Windows system
        shell_process = session.get('process')
        if not shell_process or not shell_process.stdin:
            return

        try:
            # Handle interactive mode first
            if session['in_interactive_mode']:
                # The character is being sent to the interactive process instead of the shell
                if session['interactive_process'] and session['interactive_process'].stdin:
                    try:
                        session['interactive_process'].stdin.write(command_char.encode('utf-8'))
                        session['interactive_process'].stdin.flush()
                        
                        # If the user types 'exit()' in the python interpreter, terminate the process
                        if session['buffer'].strip() == 'exit()' and command_char == '\r':
                            session['interactive_process'].terminate()
                            session['in_interactive_mode'] = False
                            session['interactive_process'] = None
                            session['interactive_reader_thread'] = None
                            session['buffer'] = ''
                            
                    except OSError:
                        print(f"Error writing to interactive process stdin for {sid}. Exiting interactive mode.")
                        session['in_interactive_mode'] = False
                        session['interactive_process'] = None
                        session['interactive_reader_thread'] = None
                        session['buffer'] = ''
                    finally:
                        if command_char != '\r':
                            session['buffer'] += command_char
                        else:
                            session['buffer'] = ''
                return

            # Normal command handling (not in interactive mode)
            # Check for backspace character
            if command_char == '\x7f' or command_char == '\b':
                if len(session['buffer']) > 0:
                    # Remove the last character from the buffer
                    session['buffer'] = session['buffer'][:-1]
                    # Send backspace, space, and backspace again to erase the character on the terminal
                    socketio.emit('terminal_output', {'data': '\b \b'}, room=sid)
            elif command_char == '\r':
                # Manually echo the newline
                socketio.emit('terminal_output', {'data': '\r\n'}, room=sid)

                # Get the command from the buffer, strip whitespace, and handle special cases
                command_to_execute = session['buffer'].strip()
                
                # Check for "cls" command and send the appropriate escape sequence
                if command_to_execute.lower() == 'cls':
                    socketio.emit('terminal_output', {'data': '\x1bc'}, room=sid)
                    session['buffer'] = ''
                    return
                
                # Check for `python` or `python.exe` command to start interactive mode
                if command_to_execute.lower().startswith('python'):
                    # Start the Python interpreter as a new subprocess
                    try:
                        python_process = subprocess.Popen(
                            ['python'],
                            stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            universal_newlines=False,
                            bufsize=0
                        )
                        session['in_interactive_mode'] = True
                        session['interactive_process'] = python_process
                        session['interactive_reader_thread'] = threading.Thread(target=read_from_process, args=(sid, python_process))
                        session['interactive_reader_thread'].daemon = True
                        session['interactive_reader_thread'].start()
                        session['buffer'] = ''
                    except FileNotFoundError:
                        socketio.emit('terminal_output', {'data': 'Error: Python interpreter not found. Please ensure python is in your system PATH.\r\n'}, room=sid)
                        session['buffer'] = ''
                    return
                
                # Ensure UTF-8 encoding is set on the first run
                if not session['has_set_encoding']:
                    shell_process.stdin.write(b'chcp 65001\n')
                    shell_process.stdin.flush()
                    session['has_set_encoding'] = True

                # Execute the buffered command
                full_command_bytes = (command_to_execute + '\n').encode('utf-8')
                shell_process.stdin.write(full_command_bytes)
                shell_process.stdin.flush()
                
                # Clear the buffer after command execution
                session['buffer'] = ''
            else:
                # Add character to buffer and echo it back to the client
                session['buffer'] += command_char
                socketio.emit('terminal_output', {'data': command_char}, room=sid)
        except OSError:
            print(f"Error writing to process stdin for {sid}. Disconnecting session.")
            del sessions[sid]


@socketio.on('disconnect')
def handle_disconnect():
    """
    Closes the PTY and terminates the shell process when a client disconnects.
    """
    sid = request.sid
    print(f'Client {sid} disconnected. Terminating their terminal process.')

    session = sessions.get(sid)
    if session:
        # Terminate the shell process if it's still running
        if session['process'] and session['process'].poll() is None:
            session['process'].terminate()
            session['process'].wait(timeout=5)
        
        # Close file descriptors for Unix systems
        if UNIX_SYSTEM:
            if session.get('master_fd'):
                os.close(session['master_fd'])
            if session.get('slave_fd'):
                os.close(session['slave_fd'])
        
        # Remove the session from our dictionary
        del sessions[sid]

# --- New SocketIO Handlers for File Management and Settings ---

@socketio.on('get_current_paths')
def handle_get_current_paths():
    """Sends the current COMMANDS_PATHS and NOTES_PATHS to the client."""
    global COMMANDS_PATHS, NOTES_PATHS
    emit('current_paths', {
        'commands_paths': COMMANDS_PATHS,
        'notes_paths': NOTES_PATHS
    }, room=request.sid)

@socketio.on('set_paths')
def handle_set_paths(data):
    """Updates the global path lists based on client input."""
    global COMMANDS_PATHS, NOTES_PATHS
    sid = request.sid
    
    # Receive new path lists from the client
    new_commands_paths_raw = data.get('commands_paths', [])
    new_notes_paths_raw = data.get('notes_paths', [])
    
    # Clean up and filter the received paths
    cleaned_commands_paths = list(set([p.strip() for p in new_commands_paths_raw if p.strip()]))
    cleaned_notes_paths = list(set([p.strip() for p in new_notes_paths_raw if p.strip()]))
    
    # Critical: Must have at least one path for each, otherwise revert/error
    if not cleaned_commands_paths or not cleaned_notes_paths:
        status_message = "\r\nError: Commands and Notes path lists cannot be empty. No changes saved.\r\n"
        emit('terminal_output', {'data': status_message}, room=sid)
        emit('paths_updated', {'success': False})
        return
        
    success = False
    status_message = "\r\nSettings Update:\r\n"
    
    # Helper to process path updates
    def process_path_update(old_paths, new_paths, dir_type):
        nonlocal success, status_message
        paths_to_save = new_paths[:] # Start with the new list
        
        # Check for new/modified paths and ensure directory creation
        for path in new_paths:
            if path not in old_paths:
                try:
                    os.makedirs(path, exist_ok=True)
                    status_message += f"- {dir_type} path added and ensured: {path}\r\n"
                    success = True
                except Exception as e:
                    status_message += f"- Error creating {dir_type} directory '{path}': {e}. Path will be ignored.\r\n"
                    if path in paths_to_save:
                        paths_to_save.remove(path)
                    
        # Check for removed paths
        for path in old_paths:
            if path not in new_paths:
                status_message += f"- {dir_type} path removed: {path}\r\n"
                success = True

        return paths_to_save

    # Process updates for both
    new_commands = process_path_update(COMMANDS_PATHS, cleaned_commands_paths, "Commands")
    new_notes = process_path_update(NOTES_PATHS, cleaned_notes_paths, "Notes")

    # If the process resulted in empty lists, prevent saving and use the current ones
    if not new_commands: new_commands = COMMANDS_PATHS
    if not new_notes: new_notes = NOTES_PATHS
    
    # Update globals only with valid, saved paths
    COMMANDS_PATHS = new_commands
    NOTES_PATHS = new_notes

    if success:
        # Save the new valid paths to the JSON file
        save_paths(COMMANDS_PATHS, NOTES_PATHS)
        emit('terminal_output', {'data': status_message}, room=sid)
        emit('paths_updated', {'success': True})
    else:
        status_message += "- No valid changes were saved.\r\n"
        emit('terminal_output', {'data': status_message}, room=sid)
        emit('paths_updated', {'success': False}) 


@socketio.on('get_files')
def handle_get_files(data):
    """
    Returns a consolidated list of all files from all paths for a specified directory type,
    including the path to distinguish them.
    """
    directory_name = data.get('directory') # "commands" or "notes"
    
    if directory_name == "commands":
        paths = COMMANDS_PATHS
    elif directory_name == "notes":
        paths = NOTES_PATHS
    else:
        emit('file_list', {'files': [], 'directory': directory_name})
        return
        
    all_files_with_path = []
    for path in paths:
        try:
            # Filter for .txt files only in notes directory
            if directory_name == "notes":
                files = [f for f in os.listdir(path) if f.endswith('.txt') and os.path.isfile(os.path.join(path, f))]
            else:
                files = [f for f in os.listdir(path) if os.path.isfile(os.path.join(path, f))]

            for f in files:
                # Store filename, the full path to the directory, and the directory type
                all_files_with_path.append({
                    'filename': f,
                    'path': path, # The exact directory path
                    'display_path': path # Used for display in the client
                })

        except Exception as e:
            print(f"Error listing files from path {path} for {directory_name}: {e}")
            # Continue to the next path
    
    emit('file_list', {'files': all_files_with_path, 'directory': directory_name})


@socketio.on('get_file_content_for_editor')
def handle_get_file_content_for_editor(data):
    """Reads the content of a specified file for the editor, given its full path."""
    sid = request.sid
    filename = data.get('filename')
    directory = data.get('directory')
    filepath_dir = data.get('path') # The specific directory path
    
    # Construct the full path using the passed path
    filepath = os.path.join(filepath_dir, filename)

    if not filename or not os.path.exists(filepath):
        emit('file_content_for_editor', {
            'content': f"Error: File '{filename}' not found at path '{filepath_dir}'.", 
            'filename': filename, 
            'directory': directory,
            'path': filepath_dir
        }, room=sid)
        return

    try:
        with open(filepath, 'r') as f:
            content = f.read()
            # Return the specific path for saving later
            emit('file_content_for_editor', {
                'content': content, 
                'filename': filename, 
                'directory': directory,
                'path': filepath_dir # CRITICAL: Send the path back to client state
            }, room=sid)
    except Exception as e:
        print(f"Error reading file {filename} for editor: {e}")
        emit('file_content_for_editor', {
            'content': f"Error reading file: {e}", 
            'filename': filename, 
            'directory': directory,
            'path': filepath_dir
        }, room=sid)

@socketio.on('save_file')
def handle_save_file(data):
    """Saves the content to a specified file, given its full path."""
    sid = request.sid
    filename = data.get('filename')
    content = data.get('content')
    filepath_dir = data.get('path') # The specific directory path
    
    # Construct the full path using the passed path
    filepath = os.path.join(filepath_dir, filename)

    if not filename or content is None or not filepath_dir:
        emit('terminal_output', {'data': f"\r\nError: Invalid data for saving file '{filename}'.\r\n"}, room=sid)
        return

    try:
        with open(filepath, 'w') as f:
            f.write(content)
        emit('terminal_output', {'data': f"\r\nSuccessfully saved file: {filename} in {filepath_dir}\r\n"}, room=sid)
    except Exception as e:
        print(f"Error saving file {filename}: {e}")
        emit('terminal_output', {'data': f"\r\nError saving file: {e}\r\n"}, room=sid)
        
@socketio.on('create_file')
def handle_create_file(data):
    """
    Creates a new file with the given name and content in the specified directory path.
    """
    sid = request.sid
    filename = data.get('filename')
    content = data.get('content')
    directory = data.get('directory')
    target_path = data.get('target_path') # The specific path chosen by the user

    if not filename or content is None or directory not in ["commands", "notes"] or not target_path:
        emit('file_creation_status', {'success': False, 'message': 'Invalid data or missing target path for file creation.'}, room=sid)
        return

    # Security check: Ensure the target_path is one of our configured paths
    valid_paths = COMMANDS_PATHS if directory == "commands" else NOTES_PATHS
    if target_path not in valid_paths:
        emit('file_creation_status', {'success': False, 'message': f'Invalid target path selected: {target_path}'}, room=sid)
        return
        
    filepath = os.path.join(target_path, filename)

    try:
        with open(filepath, 'w') as f:
            f.write(content)
        emit('file_creation_status', {'success': True, 'message': f'File created: {filename} in {target_path}'}, room=sid)
        # Refresh the file list for the client
        handle_get_files({'directory': directory})
    except Exception as e:
        print(f"Error creating file {filename} in {target_path}: {e}")
        emit('file_creation_status', {'success': False, 'message': f'Error creating file: {e}'}, room=sid)
        
@socketio.on('run_file')
def handle_run_file(data):
    """
    Reads the content of a specified file and executes each line as a command
    in the corresponding terminal session.
    """
    sid = request.sid
    session = sessions.get(sid)
    if not session:
        print(f"Session not found for {sid}")
        return

    content = data.get('content')
    if not content:
        emit('terminal_output', {'data': "\r\nError: No content to run.\r\n"}, room=sid)
        return

    try:
        # Split the content by lines and run each command
        for line in content.splitlines():
            command_line = line.strip()
            if command_line:
                # --- FIX FOR UNIX/LINUX SYSTEMS ---
                if UNIX_SYSTEM:
                    # For Unix/Linux, write directly to the PTY's master file descriptor
                    master_fd = session.get('master_fd')
                    if master_fd:
                        os.write(master_fd, (command_line + '\n').encode('utf-8'))
                        # Sleep is important to allow the command to execute and the
                        # output to be processed before sending the next command.
                        time.sleep(0.5)
                else:
                    # For Windows, write to the subprocess's stdin
                    shell_process = session.get('process')
                    if shell_process and shell_process.stdin:
                        shell_process.stdin.write((command_line + '\n').encode('utf-8'))
                        shell_process.stdin.flush()
                        time.sleep(0.5)

    except Exception as e:
        print(f"Error running content: {e}")
        emit('terminal_output', {'data': f"\r\nError running content: {e}\r\n"}, room=sid)

if __name__ == '__main__':
    # Ensure the commands directory is ready before starting the app
    setup_directories()

    port = 5001
    if '--port' in sys.argv:
        try:
            port_index = sys.argv.index('--port') + 1
            port = int(sys.argv[port_index])
        except (ValueError, IndexError):
            print("Warning: Invalid or missing port argument. Using default port.")
    
    print(f"Terminal sub-app is starting on port {port}...")
    socketio.run(app, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)