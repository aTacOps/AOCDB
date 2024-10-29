import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import tkinter.font as tkFont
import requests
import json
from datetime import datetime, timedelta
import pytz

class FirebaseService:
    def __init__(self):
        # Replace with your Firebase project configuration
        self.api_key = 'API KEY'  # Replace with your API Key
        self.project_id = 'PorjectID'  # Replace with your Project ID
        self.auth_url = 'https://identitytoolkit.googleapis.com/v1/accounts'
        self.database_url = f'https://firestore.googleapis.com/v1/projects/{self.project_id}/databases/(default)/documents'
        self.user = None  # Will hold user info after authentication
        self.id_token = None  # User's ID token
        self.user_role = 'unverified'  # Default role is 'unverified'

    def create_user(self, email, password, discord_name):
        url = f'{self.auth_url}:signUp?key={self.api_key}'
        payload = {
            'email': email,
            'password': password,
            'returnSecureToken': True
        }
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            self.user = response.json()
            self.id_token = self.user['idToken']
            user_id = self.user['localId']

            print("User successfully registered.")
            print(f"Assigning default role to user ID: {user_id}")

            # Automatically assign 'unverified' role upon registration
            self.assign_default_role(user_id, email, discord_name)
            return self.user
        else:
            error_message = response.json()['error']['message']
            raise Exception(error_message)

    def assign_default_role(self, user_id, email, discord_name):
        # Assign default role 'unverified' to new users in Firestore
        url = f'{self.database_url}/users/{user_id}'
        headers = {
            'Authorization': f'Bearer {self.id_token}',
            'Content-Type': 'application/json'
        }
        firestore_data = {
            'fields': {
                'email': {'stringValue': email},
                'Discord': {'stringValue': discord_name},
                'role': {'stringValue': 'unverified'}  # Default role
            }
        }
        response = requests.patch(url, headers=headers, json=firestore_data)
        if response.status_code != 200:
            raise Exception("Failed to assign default role.")

    def sign_in_user(self, email, password):
        url = f'{self.auth_url}:signInWithPassword?key={self.api_key}'
        payload = {
            'email': email,
            'password': password,
            'returnSecureToken': True
        }
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            self.user = response.json()
            self.id_token = self.user['idToken']
            print(f"User authenticated. ID Token: {self.id_token}")  # Debugging: print the ID token
            return self.user
        else:
            error_message = response.json()['error']['message']
            raise Exception(error_message)

    def fetch_user_role(self, user_id):
        url = f'{self.database_url}/users/{user_id}'
        headers = {
            'Authorization': f'Bearer {self.id_token}'
        }
        response = requests.get(url, headers=headers)

        if response.status_code == 200:
            firestore_data = response.json()
            print(f"Firestore response: {firestore_data}")  # Debugging output
            try:
                self.user_role = firestore_data['fields']['role']['stringValue']
                print(f"User role fetched: {self.user_role}")  # Debugging output
            except KeyError:
                print("Role field not found. Setting role to 'unverified'.")
                self.user_role = 'unverified'
        else:
            print(f"Failed to fetch user document: {response.status_code} {response.json()}")
            self.user_role = 'unverified'

        return self.user_role

    def check_user_permission(self):
        # Ensure that only users with the 'user' role can access the database
        if self.user_role != 'user':
            raise Exception("Access Denied: Your account is not verified yet.")

    def add_or_update_player(self, player_data):
        if not self.id_token:
            raise Exception("User not authenticated")

        # Use the player's name (lowercased) as the document ID
        doc_name = player_data['Name'].lower()
        url = f'{self.database_url}/players/{doc_name}'

        headers = {
            'Authorization': f'Bearer {self.id_token}',
            'Content-Type': 'application/json'
        }

        # Fetch the existing player data (if any) for comparison
        try:
            existing_player_data = self.get_player_by_name(player_data['Name'])
        except Exception as e:
            print(f"Error fetching existing player data: {e}")
            existing_player_data = None

        # Attach metadata (who made the change and when)
        current_time_iso = self.get_adjusted_timestamp()
        player_data['updatedBy'] = self.user['email']
        player_data['updatedAt'] = current_time_iso  # Store timestamp

        # Convert player data to Firestore document format
        firestore_data = {'fields': self.dict_to_firestore_fields(player_data)}

        # Send PATCH request to create or update the document
        response = requests.patch(url, headers=headers, json=firestore_data)
        if response.status_code not in [200, 201]:
            error_message = response.json()
            raise Exception(f"Failed to add/update player: {error_message}")
        else:
            print(f"Player '{player_data['Name']}' added/updated successfully.")

        # Determine the type of change (added or updated) and what fields were changed
        if existing_player_data:
            # If player exists, find the differences between old and new data
            changes = self.compare_player_data(existing_player_data, player_data)
            action_type = "update"
        else:
            # If no existing data, it's a new player
            changes = {"action": "added new player"}
            action_type = "add"

        # Log the action in the 'logs' collection with detailed changes
        self.log_user_action(action_type=action_type, player_name=player_data['Name'], changes=changes)

    def compare_player_data(self, old_data, new_data):
        """
        Compare old and new player data and return a dictionary with the changes.
        """
        changes = {}
        for key in new_data:
            old_value = old_data.get(key)
            new_value = new_data.get(key)
            if old_value != new_value:
                changes[key] = {"old": old_value, "new": new_value}
        return changes

    def log_user_action(self, action_type, player_name, changes):
        """
        Logs the user actions like adding, updating, or deleting a player.
        """
        user_id = self.user['localId']
        email = self.user['email']

        # Firestore expects timestamps to be in the format for protobuf.Timestamp
        current_time = datetime.now(pytz.UTC).isoformat()

        log_data = {
            'fields': {
                'userId': {'stringValue': user_id},
                'email': {'stringValue': email},
                'actionType': {'stringValue': action_type},
                'playerName': {'stringValue': player_name},
                'timestamp': {'timestampValue': current_time},  # Correct format for timestamp
                'changes': {'stringValue': json.dumps(changes)}
            }
        }

        # Send the log to Firestore
        log_url = f'{self.database_url}/logs'
        headers = {
            'Authorization': f'Bearer {self.id_token}',
            'Content-Type': 'application/json'
        }
        response = requests.post(log_url, headers=headers, json=log_data)

        if response.status_code not in [200, 201]:
            print(f"Failed to log action: {response.json()}")

    def get_adjusted_timestamp(self):
        """
        Get the current UTC time, adjust by 4 hours earlier, remove microseconds,
        and format the time in ISO 8601 format with 'T' separator and 'Z' for UTC.
        """
        # Get the current UTC time
        current_time_utc = datetime.now(pytz.UTC)

        # Shift the time by 4 hours earlier
        adjusted_time = current_time_utc - timedelta(hours=4)

        # Format the time in ISO 8601 format without microseconds, ending with 'Z' (UTC)
        formatted_time = adjusted_time.replace(microsecond=0).isoformat(timespec='seconds') + 'Z'

        return formatted_time

    def get_player_by_name(self, name):
        self.check_user_permission()  # Check if user has 'user' role
        doc_name = name.lower()
        url = f'{self.database_url}/players/{doc_name}'
        headers = {
            'Authorization': f'Bearer {self.id_token}'
        }
        response = requests.get(url, headers=headers)
        print(f"Fetching player '{name}' from Firestore.")
        print(f"Response status code: {response.status_code}")
        print(f"Response content: {response.content}")
        if response.status_code == 200:
            try:
                firestore_data = response.json()
                # Check if 'fields' key exists
                if 'fields' in firestore_data:
                    player_data = self.firestore_fields_to_dict(firestore_data['fields'])
                    return player_data
                else:
                    print(f"No 'fields' in firestore_data for player {name}: {firestore_data}")
                    return None
            except json.JSONDecodeError as e:
                print(f"JSON decoding error: {e}")
                return None
        elif response.status_code == 404:
            print(f"Player '{name}' not found in Firestore.")
            return None
        else:
            print(f"Failed to fetch player {name}: {response.status_code} {response.content}")
            return None

    def get_all_players(self):
        if not self.id_token:
            raise Exception("User not authenticated")

        url = f'{self.database_url}/players'

        headers = {
            'Authorization': f'Bearer {self.id_token}',
        }

        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            firestore_data = response.json()
            players = []
            for document in firestore_data.get('documents', []):
                if 'fields' in document:
                    player_data = self.firestore_fields_to_dict(document['fields'])
                    players.append(player_data)
                else:
                    print(f"No 'fields' in document: {document}")
            return players
        else:
            raise Exception(f"Failed to fetch players: {response.json()}")


    def get_all_discordNames(self):
        discord_Name = {}
        players = self.get_all_players()
        for player in players:
            discordName = player.get('Discord')
            if discordName and discordName != 'N/A':
                if discordName not in discord_Name:
                    discord_Name[discordName] = []
                discord_Name[discordName].append(player)
        return discord_Name

    def get_all_guilds(self):
        # Add this method to fetch all guilds and their members from Firebase
        guilds = {}
        players = self.get_all_players()
        for player in players:
            guild_name = player.get('Guild')
            if guild_name and guild_name != 'N/A':
                if guild_name not in guilds:
                    guilds[guild_name] = []
                guilds[guild_name].append(player)
        return guilds

    def export_to_markdown(self, players, guilds, discord_Name):
        """
        Exports the player and guild data to markdown files with links to known associates and guild members.
        """
        player_path = r"C:LOCALPATH"
        guild_path = r"C:LOCALPATH" #Be sure to enter your own path here.
        discord_path = r"C:LOCALPATH"

        # Ensure output directories exist
        os.makedirs(player_path, exist_ok=True)
        os.makedirs(guild_path, exist_ok=True)
        os.makedirs(discord_path, exist_ok=True)

        # Export player files with links to known associates, discord names, and guilds
        for player in players:
            player_name = player.get('Name', 'Unknown')
            player_file_path = os.path.join(player_path, f"{player_name}.md")

            with open(player_file_path, "w") as player_file:
                player_file.write(f"# {player_name}\n")
                player_file.write(f"- **Level**: {player.get('Level', 'N/A')}\n")
                player_file.write(f"- **Class**: {player.get('Class', 'N/A')}\n")
                player_file.write(f"- **Hostile Status**: {player.get('Hostile Status', 'N/A')}\n")
                player_file.write(f"- **Subclass**: {player.get('Subclass', 'N/A')}\n")
                guild = player.get('Guild', 'N/A')
                if guild != 'N/A':
                    player_file.write(f"- **Guild**: [{guild}](../Guilds/{guild}.md)\n")
                else:
                    player_file.write(f"- **Guild**: N/A\n")

                # Known Associates
                associates = player.get('Known Associates', [])
                if associates:
                    player_file.write("\n## Known Associates\n")
                    for associate in associates:
                        player_file.write(f"- [{associate}](../Players/{associate}.md)\n")

                # Discord name
                if player.get('Discord'):
                    discord_name = player['Discord']
                    player_file.write(f"\n- **Discord Name**: [{discord_name}](../Discord/{discord_name}.md)\n")

        # Export guild files with links to members
        for guild_name, members in guilds.items():
            guild_file_path = os.path.join(guild_path, f"{guild_name}.md")

            with open(guild_file_path, "w") as guild_file:
                guild_file.write(f"# Guild: {guild_name}\n\n")
                guild_file.write("## Members\n")
                for member in members:
                    guild_file.write(f"- [{member['Name']}](../Players/{member['Name']}.md)\n")

        # Export discord files with links to Players
        for discordName, chars in discord_Name.items():
            discord_file_path = os.path.join(discord_path, f"{discordName}.md")

            with open(discord_file_path, "w") as discord_file:
                discord_file.write(f"# Discord: {discordName}\n\n")
                discord_file.write("## Characters\n")
                for char in chars:
                    discord_file.write(f"- [{char['Name']}](../Players/{char['Name']}.md)\n")

        print("Export completed.")

    def dict_to_firestore_fields(self, data_dict):
        fields = {}
        for key, value in data_dict.items():
            if isinstance(value, int):
                fields[key] = {'integerValue': str(value)}
            elif isinstance(value, list):
                # Handle lists, specifically for Known Associates
                fields[key] = {'arrayValue': {'values': [{'stringValue': item} for item in value]}}
            else:
                fields[key] = {'stringValue': value}
        return fields

    def firestore_fields_to_dict(self, fields_dict):
        data = {}
        for key, value_dict in fields_dict.items():
            if 'stringValue' in value_dict:
                data[key] = value_dict['stringValue']
            elif 'integerValue' in value_dict:
                data[key] = int(value_dict['integerValue'])
            elif 'arrayValue' in value_dict:
                array_values = value_dict['arrayValue'].get('values', [])
                data[key] = [item.get('stringValue', '') for item in array_values]
            else:
                data[key] = None
        return data

# The rest of your code (PlayerManagementApp and main execution) remains the same.
# Ensure that all methods are properly indented and defined.


class PlayerManagementApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Player Management System")

        # Set the root window's background color to black
        self.root.configure(bg='black')

        # Define the default font
        default_font = tkFont.nametofont("TkDefaultFont")
        default_font.configure(family='Helvetica', size=10)

        # Apply the default font to the root window
        self.root.option_add('*Font', default_font)

        # Create and configure ttk styles
        self.style = ttk.Style()
        self.style.theme_use('clam')

        # Configure styles for ttk widgets
        self.style.configure('.', background='black', foreground='white')
        self.style.configure('TLabel', background='black', foreground='white')
        self.style.configure('TButton', background='black', foreground='white')
        self.style.configure('TEntry', fieldbackground='gray20', foreground='white')
        self.style.configure('TCheckbutton', background='black', foreground='white', selectcolor='black')
        self.style.configure('TLabelframe', background='black', foreground='white')
        self.style.configure('TLabelframe.Label', background='black', foreground='white')
        self.style.configure('Treeview', background='black', foreground='white', fieldbackground='black')
        self.style.map('Treeview', background=[('selected', 'gray20')], foreground=[('selected', 'white')])

        # Configure custom Combobox style
        self.style.configure('CustomCombobox.TCombobox',
                             fieldbackground='gray20',
                             background='gray20',
                             foreground='white',
                             arrowcolor='white')

        # Initialize Firebase service
        self.firebase_service = FirebaseService()

        # Create the login screen
        self.create_login_screen()

    def create_login_screen(self):
        self.login_frame = tk.Frame(self.root, bg='black')
        self.login_frame.pack(expand=True)

        tk.Label(self.login_frame, text="Email:", bg='black', fg='white').grid(row=0, column=0, sticky='e', padx=5, pady=5)
        self.email_entry = tk.Entry(self.login_frame, bg='gray20', fg='white')
        self.email_entry.grid(row=0, column=1, padx=5, pady=5)

        tk.Label(self.login_frame, text="Password:", bg='black', fg='white').grid(row=1, column=0, sticky='e', padx=5, pady=5)
        self.password_entry = tk.Entry(self.login_frame, show='*', bg='gray20', fg='white')
        self.password_entry.grid(row=1, column=1, padx=5, pady=5)

        tk.Label(self.login_frame, text="Discord Name:", bg='black', fg='white').grid(row=2, column=0, sticky='e', padx=5, pady=5)
        self.discord_entry = tk.Entry(self.login_frame, bg='gray20', fg='white')
        self.discord_entry.grid(row=2, column=1, padx=5, pady=5)

        self.login_button = tk.Button(self.login_frame, text="Login", command=self.login_user, bg='black', fg='white')
        self.login_button.grid(row=3, column=0, padx=5, pady=10)

        self.register_button = tk.Button(self.login_frame, text="Register", command=self.register_user, bg='black', fg='white')
        self.register_button.grid(row=3, column=1, padx=5, pady=10)

    def login_user(self):
        email = self.email_entry.get()
        password = self.password_entry.get()
        try:
            # Authenticate user
            self.firebase_service.sign_in_user(email, password)

            # Fetch user ID after successful login
            user_id = self.firebase_service.user['localId']

            # Fetch the user role (only once, unless it's not fetched)
            user_role = self.firebase_service.fetch_user_role(user_id)

            print(f"User role after login: {user_role}")  # Debugging output

            # Check if the user role is 'user'
            if user_role == "user":
                messagebox.showinfo("Login Successful", f"Welcome, {email}!")
                self.login_frame.destroy()
                self.create_main_interface()
            else:
                messagebox.showerror("Access Denied", "Your account is not yet verified.")
        except Exception as e:
            messagebox.showerror("Login Failed", str(e))

    def register_user(self):
        email = self.email_entry.get()
        password = self.password_entry.get()
        discord_name = self.discord_entry.get()
        try:
            self.firebase_service.create_user(email, password, discord_name)
            messagebox.showinfo("Registration Successful", f"Account created for {email}. You can now log in.")
        except Exception as e:
            messagebox.showerror("Registration Failed", str(e))

    def create_main_interface(self):
        # Create a Notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill='both')

        # Create frames for each tab with black background
        self.manage_frame = ttk.Frame(self.notebook)
        self.view_frame = ttk.Frame(self.notebook)
        self.manage_frame.configure(style='TFrame')
        self.view_frame.configure(style='TFrame')
        self.notebook.add(self.manage_frame, text='Manage Players')
        self.notebook.add(self.view_frame, text='View Players')

        # Manage Players Tab
        self.create_manage_tab()

        # View Players Tab
        self.create_view_tab()

        # Update Markdown Button
        update_button = tk.Button(
            self.manage_frame,
            text="Update Markdown Files",
            command=self.update_markdown_files,
            bg='black',
            fg='white'
        )
        update_button.pack(fill='x', padx=10, pady=10)

    def update_markdown_files(self):
        try:
            # Fetch players and guilds from Firebase
            players = self.firebase_service.get_all_players()
            guilds = self.firebase_service.get_all_guilds()
            discord = self.firebase_service.get_all_discordNames()
            # Export the data to markdown files
            self.firebase_service.export_to_markdown(players, guilds, discord)
            messagebox.showinfo("Success", "Markdown files updated successfully.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update markdown files: {str(e)}")

    def create_manage_tab(self):
        # Add Player Button
        self.add_player_button = tk.Button(
            self.manage_frame, text="Add Player",
            command=self.add_player, bg='black', fg='white'
        )
        self.add_player_button.pack(fill='x', padx=10, pady=5)

        # Update Player Button
        self.update_player_button = tk.Button(
            self.manage_frame, text="Update Player",
            command=self.update_player, bg='black', fg='white'
        )
        self.update_player_button.pack(fill='x', padx=10, pady=5)

        # Search Player by Name
        self.search_button = tk.Button(
            self.manage_frame, text="Search Player by Name",
            command=self.search_player, bg='black', fg='white'
        )
        self.search_button.pack(fill='x', padx=10, pady=5)

        # Logout Button
        self.logout_button = tk.Button(
            self.manage_frame, text="Logout", command=self.logout_user, bg='black', fg='white'
        )
        self.logout_button.pack(fill='x', padx=10, pady=5)

    def logout_user(self):
        confirm = messagebox.askyesno("Logout", "Are you sure you want to logout?")
        if confirm:
            self.notebook.destroy()
            self.firebase_service.user = None
            self.firebase_service.id_token = None
            self.create_login_screen()

    def add_player(self):
        self.add_or_update_player(is_update=False)

    def update_player(self):
        name = simpledialog.askstring("Update Player", "Enter player name:")
        if name:
            player = self.firebase_service.get_player_by_name(name)
            if player:
                self.add_or_update_player(is_update=True, player=player)
            else:
                messagebox.showinfo("Not Found", f"No player named '{name}' found.")
        else:
            messagebox.showwarning("Input Error", "Player name cannot be empty.")

    def search_player(self):
        name = simpledialog.askstring("Search Player", "Enter player name:")
        if name:
            player = self.firebase_service.get_player_by_name(name)
            if player:
                self.show_player_info(player)
            else:
                messagebox.showinfo("Not Found", f"No player named '{name}'.")
        else:
            messagebox.showwarning("Input Error", "Player name cannot be empty.")

    def add_or_update_player(self, is_update=False, player=None):
        """
        Opens a window to add or update a player, with an input for Known Associates.
        """
        self.new_window = tk.Toplevel(self.root)
        self.new_window.title("Update Player" if is_update else "Add Player")
        self.new_window.configure(bg='black')

        # Player Name
        tk.Label(self.new_window, text="Player Name:", bg='black', fg='white').grid(row=0, column=0, sticky='e', padx=5, pady=5)
        name_entry = tk.Entry(self.new_window, bg='gray20', fg='white')
        name_entry.grid(row=0, column=1, sticky='w', padx=5, pady=5)
        if is_update:
            name_entry.insert(0, player['Name'])
            name_entry.config(state='disabled')

        # Player Level
        tk.Label(self.new_window, text="Player Level (1-50):", bg='black', fg='white').grid(row=1, column=0, sticky='e', padx=5, pady=5)
        level_var = tk.StringVar()
        level_entry = tk.Entry(self.new_window, textvariable=level_var, bg='gray20', fg='white')
        level_entry.grid(row=1, column=1, sticky='w', padx=5, pady=5)
        if is_update:
            level_var.set(str(player['Level']))


        # Player Class
        tk.Label(self.new_window, text="Player Class:", bg='black', fg='white').grid(row=2, column=0, sticky='e', padx=5, pady=5)
        class_entry = tk.Entry(self.new_window, bg='gray20', fg='white')
        class_entry.grid(row=2, column=1, sticky='w', padx=5, pady=5)
        if is_update:
            class_entry.insert(0, player['Class'])

        # Subclass
        tk.Label(self.new_window, text="Subclass:", bg='black', fg='white').grid(row=3, column=0, sticky='e', padx=5, pady=5)
        subclass_entry = tk.Entry(self.new_window, bg='gray20', fg='white')
        subclass_entry.grid(row=3, column=1, sticky='w', padx=5, pady=5)
        if is_update:
            subclass_entry.insert(0, player.get('Subclass', ''))
        else:
            subclass_entry.config(state='disabled')

        # Bind level_var to update subclass_entry
        level_var.trace('w', lambda *args: self.update_subclass_entry(subclass_entry, level_var))
        if is_update:
            # Update subclass_entry initial state based on current level
            self.update_subclass_entry(subclass_entry, level_var)

        # Hostile Status
        tk.Label(self.new_window, text="Hostile Status:", bg='black', fg='white').grid(row=4, column=0, sticky='e', padx=5, pady=5)
        status_var = tk.StringVar()
        if is_update:
            status_var.set(player['Hostile Status'].lower())
        else:
            status_var.set('neutral')
        status_menu = ttk.Combobox(self.new_window, textvariable=status_var, values=['friendly', 'neutral', 'hostile'], state='readonly', style='CustomCombobox.TCombobox')
        status_menu.grid(row=4, column=1, sticky='w', padx=5, pady=5)

        # Known Associates
        tk.Label(self.new_window, text="Known Associates (comma-separated):", bg='black', fg='white').grid(row=5, column=0, sticky='e', padx=5, pady=5)
        associates_entry = tk.Entry(self.new_window, bg='gray20', fg='white')
        associates_entry.grid(row=5, column=1, sticky='w', padx=5, pady=5)
        # Pre-fill Known Associates if updating an existing player
        if is_update:
            known_associates = player.get('Known Associates', [])
            # Ensure known_associates is a list
            if isinstance(known_associates, str):
                known_associates = [known_associates]  # Wrap single string in a list
            elif not isinstance(known_associates, list):
                known_associates = []
            associates_entry.insert(0, ', '.join(known_associates))

        # Discord Information
        tk.Label(self.new_window, text="Discord Name:", bg='black', fg='white').grid(row=6, column=0, sticky='e', padx=5, pady=5)
        discord_entry = tk.Entry(self.new_window, bg='gray20', fg='white')
        discord_entry.grid(row=6, column=1, sticky='w', padx=5, pady=5)
        if is_update:
            discord_entry.insert(0, player.get('Discord', ''))

        # Guild Information
        guild_var = tk.BooleanVar(value=player.get('Guild', 'N/A') != 'N/A' if is_update else False)
        guild_rank_known_var = tk.BooleanVar(value=player.get('Guild Rank', 'N/A') != 'Unknown' if is_update else False)

        tk.Checkbutton(
            self.new_window, text="In a Guild?", variable=guild_var,
            command=lambda: self.toggle_guild_fields(
                guild_var.get(), guild_rank_known_var.get(), guild_name_entry, guild_rank_entry
            ),
            bg='black', fg='white', selectcolor='black'
        ).grid(row=7, column=0, sticky='e')

        tk.Checkbutton(
            self.new_window, text="Guild Rank Known?", variable=guild_rank_known_var,
            command=lambda: self.toggle_guild_fields(
                guild_var.get(), guild_rank_known_var.get(), guild_name_entry, guild_rank_entry
            ),
            bg='black', fg='white', selectcolor='black'
        ).grid(row=8, column=0, sticky='e')

        # Guild Name and Rank Entries
        guild_name_entry = tk.Entry(self.new_window, bg='gray20', fg='white')
        guild_rank_entry = tk.Entry(self.new_window, bg='gray20', fg='white')
        guild_name_entry.grid(row=7, column=1, sticky='w')
        guild_rank_entry.grid(row=8, column=1, sticky='w')

        if is_update:
            guild_name_entry.insert(0, player.get('Guild', ''))
            guild_rank_entry.insert(0, player.get('Guild Rank', ''))

        # Notes
        tk.Label(self.new_window, text="Notes:", bg='black', fg='white').grid(row=10, column=0, sticky='ne', padx=5, pady=5)
        notes_text = tk.Text(self.new_window, height=4, width=30, bg='gray20', fg='white', insertbackground='white')
        notes_text.grid(row=10, column=1, sticky='w', padx=5, pady=5)
        if is_update:
            notes_text.insert("1.0", player.get('Notes', ''))

        # Submit Button
        if is_update:
            submit_command = lambda: self.submit_player_update(
                player,
                name_entry.get(),
                level_entry.get(),
                subclass_entry.get(),
                class_entry.get(),
                discord_entry.get(),
                guild_var.get(),
                guild_rank_known_var.get(),
                guild_name_entry.get(),
                guild_rank_entry.get(),
                status_var.get(),
                notes_text.get("1.0", tk.END),
                associates=associates_entry.get()
            )
        else:
            submit_command = lambda: self.submit_player(
                name_entry.get(),
                level_entry.get(),
                subclass_entry.get(),
                class_entry.get(),
                discord_entry.get(),
                guild_var.get(),
                guild_rank_known_var.get(),
                guild_name_entry.get(),
                guild_rank_entry.get(),
                status_var.get(),
                notes_text.get("1.0", tk.END),
                associates=associates_entry.get()
            )

        submit_button = tk.Button(
            self.new_window,
            text="Update" if is_update else "Add",
            command=submit_command,
            bg='black',
            fg='white'
        )
        submit_button.grid(row=13, column=1, sticky='e', padx=5, pady=10)

        self.toggle_guild_fields(guild_var.get(), guild_rank_known_var.get(), guild_name_entry, guild_rank_entry)

    def update_subclass_entry(self, subclass_entry, level_var):
        try:
            level = int(level_var.get())
            if level >= 25:
                subclass_entry.config(state='normal')
            else:
                subclass_entry.delete(0, 'end')
                subclass_entry.insert(0, 'Unavailable')
                subclass_entry.config(state='disabled')
        except ValueError:
            # If the level is not a valid integer
            subclass_entry.delete(0, 'end')
            subclass_entry.insert(0, '')
            subclass_entry.config(state='disabled')


    def toggle_guild_fields(self, in_guild, guild_rank_known, guild_name_entry, guild_rank_entry):
        """
        Enable or disable the guild name and guild rank fields based on the checkboxes.
        """
        if in_guild:
            guild_name_entry.config(state='normal')
            if guild_rank_known:
                guild_rank_entry.config(state='normal')
            else:
                guild_rank_entry.delete(0, 'end')
                guild_rank_entry.config(state='disabled')
        else:
            guild_name_entry.delete(0, 'end')
            guild_name_entry.config(state='disabled')
            guild_rank_entry.delete(0, 'end')
            guild_rank_entry.config(state='disabled')

    def submit_player(self, name, level, subclass, player_class, discordName, in_guild, guild_rank_known, guild_name, guild_rank, status, notes, associates=[]):
        try:
            level = int(level)
            if not (1 <= level <= 50):
                raise ValueError("Level must be between 1 and 50.")

            # Process guild information
            guild_info = {'name': 'N/A', 'rank': 'N/A'}
            if in_guild:
                if not guild_name.strip():
                    raise ValueError("Guild name cannot be empty if in a guild.")
                guild_info['name'] = guild_name.strip()
                guild_info['rank'] = guild_rank.strip() if guild_rank_known else 'Unknown'

            player_data = {
                'Name': name.strip(),
                'Level': level,
                'Class': player_class.strip(),
                'Subclass': subclass.strip() if level >= 25 else 'Unavailable',
                'Hostile Status': status.capitalize(),
                'Guild': guild_info['name'],
                'Guild Rank': guild_info['rank'],
                'Notes': notes.strip(),
                'Discord': discordName.strip(),
                'Known Associates': [associate.strip() for associate in associates.split(',') if associate.strip()]
            }

            self.firebase_service.add_or_update_player(player_data)
            messagebox.showinfo("Success", "Player added.")
            self.new_window.destroy()
            self.apply_filters()
        except ValueError as e:
            messagebox.showerror("Input Error", f"Invalid input: {e}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def submit_player_update(self, player, name, level, subclass, player_class, discordName, in_guild, guild_rank_known, guild_name, guild_rank, status, notes, associates=[]):
        try:
            # Process level and validate
            level = int(level)
            if not (1 <= level <= 50):
                raise ValueError("Level must be between 1 and 50.")

            # Validate name and class
            if not name.strip():
                raise ValueError("Player name cannot be empty.")
            if not player_class.strip():
                raise ValueError("Player class cannot be empty.")

            # Process guild information
            guild_info = {'name': 'N/A', 'rank': 'N/A'}
            if in_guild:
                if not guild_name.strip():
                    raise ValueError("Guild name cannot be empty if in a guild.")
                guild_info['name'] = guild_name.strip()
                guild_info['rank'] = guild_rank.strip() if guild_rank_known else 'Unknown'

            # Prepare updated player data
            player_data = {
                'Name': name.strip(),
                'Level': level,
                'Class': player_class.strip(),
                'Subclass': subclass.strip() if level >= 25 else 'Unavailable',
                'Hostile Status': status.capitalize(),
                'Guild': guild_info['name'],
                'Guild Rank': guild_info['rank'],
                'Notes': notes.strip(),
                'Discord': discordName.strip(),
                'Known Associates': [associate.strip() for associate in associates.split(',') if associate.strip()]
            }

            # Update the primary player's data in Firebase
            self.firebase_service.add_or_update_player(player_data)

            # Ensure reciprocal links in known associates
            for associate_name in player_data['Known Associates']:
                # Fetch associate data to check if they already exist in Firebase
                associate_data = self.firebase_service.get_player_by_name(associate_name)

                if associate_data:
                    # Add primary player as a known associate of the associate if not already listed
                    if name not in associate_data.get('Known Associates', []):
                        associate_data.setdefault('Known Associates', []).append(name)
                        self.firebase_service.add_or_update_player(associate_data)

            # Notify success and close update window
            messagebox.showinfo("Success", "Player information and associates updated.")

            # Update markdown files for the player and their associates
            self.update_markdown_files()

        except ValueError as e:
            messagebox.showerror("Input Error", f"Invalid input: {e}")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def create_view_tab(self):
        """
        Sets up the view tab with filters and displays the list of players.
        """
        filters_frame = ttk.LabelFrame(self.view_frame, text="Filters")
        filters_frame.pack(fill='x', padx=10, pady=5)

        # Filter Variables
        self.filter_class = tk.StringVar()
        self.filter_status = tk.StringVar()
        self.filter_guild = tk.StringVar()

        # Class Filter
        tk.Label(filters_frame, text="Class:", bg='black', fg='white').grid(row=0, column=0, sticky='e')
        class_entry = tk.Entry(filters_frame, textvariable=self.filter_class, bg='gray20', fg='white')
        class_entry.grid(row=0, column=1, sticky='w')

        # Status Filter
        tk.Label(filters_frame, text="Hostile Status:", bg='black', fg='white').grid(row=1, column=0, sticky='e')
        status_entry = tk.Entry(filters_frame, textvariable=self.filter_status, bg='gray20', fg='white')
        status_entry.grid(row=1, column=1, sticky='w')

        # Guild Filter
        tk.Label(filters_frame, text="Guild:", bg='black', fg='white').grid(row=2, column=0, sticky='e')
        guild_entry = tk.Entry(filters_frame, textvariable=self.filter_guild, bg='gray20', fg='white')
        guild_entry.grid(row=2, column=1, sticky='w')

        # Sort By Option
        tk.Label(filters_frame, text="Sort By:", bg='black', fg='white').grid(row=3, column=0, sticky='e')
        self.sort_by_var = tk.StringVar()
        sort_options = ['Name', 'Level', 'Class', 'Hostile Status', 'Guild']
        self.sort_by_var.set('Name')
        sort_menu = ttk.Combobox(filters_frame, textvariable=self.sort_by_var, values=sort_options, state='readonly', style='CustomCombobox.TCombobox')
        sort_menu.current(0)
        sort_menu.grid(row=3, column=1, sticky='w', padx=5, pady=5)

        # Apply Filters Button
        apply_button = tk.Button(filters_frame, text="Apply Filters", command=self.apply_filters, bg='black', fg='white')
        apply_button.grid(row=4, column=1, sticky='w', pady=5)

        # Player Count Label
        self.player_count_label = tk.Label(self.view_frame, text="Total Players: 0", bg='black', fg='white')
        self.player_count_label.pack(anchor='se', padx=10, pady=10)

        # Players List
        self.players_tree = ttk.Treeview(self.view_frame, columns=('Name', 'Level', 'Class', 'Hostile Status', 'Guild'), show='headings', style='Treeview')
        self.players_tree.heading('Name', text='Name')
        self.players_tree.heading('Level', text='Level')
        self.players_tree.heading('Class', text='Class')
        self.players_tree.heading('Hostile Status', text='Hostile Status')
        self.players_tree.heading('Guild', text='Guild')
        self.players_tree.pack(expand=True, fill='both', padx=10, pady=5)

        for col in ('Name', 'Level', 'Class', 'Hostile Status', 'Guild'):
            self.players_tree.heading(col, text=col, anchor='w')

        # Bind double-click to view player details
        self.players_tree.bind('<Double-1>', self.on_player_double_click)

        # Load initial data
        self.apply_filters()

    def apply_filters(self):
        try:
            all_players = self.firebase_service.get_all_players()
            if not all_players:
                messagebox.showinfo("Info", "No players found.")
                return

            filters = {
                'Class': self.filter_class.get(),
                'Hostile Status': self.filter_status.get(),
                'Guild': self.filter_guild.get()
            }
            sort_by = self.sort_by_var.get()

            # Apply filters
            filtered_data = all_players
            for key, value in filters.items():
                if value:
                    filtered_data = [player for player in filtered_data if player.get(key, '').lower() == value.lower()]

            # Sort data
            if sort_by:
                try:
                    if sort_by == 'Level':
                        filtered_data.sort(key=lambda x: x.get(sort_by, 0))
                    else:
                        filtered_data.sort(key=lambda x: x.get(sort_by, '').lower())
                except KeyError:
                    pass

            # Clear existing data
            for item in self.players_tree.get_children():
                self.players_tree.delete(item)

            # Insert new data
            for player in filtered_data:
                # Prepare the Guild column value
                guild_name = player.get('Guild', 'N/A')
                guild_rank = player.get('Guild Rank', '')

                # Check if guild rank is not 'Unknown' and not empty
                if guild_rank and guild_rank.lower() != 'unknown':
                    guild_display = f"{guild_name} ({guild_rank})"
                else:
                    guild_display = guild_name

                # Insert the player data, including 'Name'
                self.players_tree.insert('', 'end', values=(
                    player.get('Name', ''),
                    player.get('Level', ''),
                    player.get('Class', ''),
                    player.get('Hostile Status', ''),
                    guild_display
                ))

            # Update the player count label with the total number of filtered players
            total_players = len(filtered_data)
            self.player_count_label.config(text=f"Total Players: {total_players}")

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred while applying filters: {str(e)}")


    def on_player_double_click(self, event):
        item = self.players_tree.selection()
        if item:
            item = item[0]
            values = self.players_tree.item(item, 'values')
            player_name = values[0]  # 'Name' is the first column
            player = self.firebase_service.get_player_by_name(player_name)
            if player:
                self.show_player_info(player)

    def show_player_info(self, player):
        info_window = tk.Toplevel(self.root)
        info_window.title(f"Player: {player['Name']}")
        info_window.configure(bg='black')

        row = 0
        for key in ['Name', 'Level', 'Subclass', 'Class', 'Guild',
                    'Guild Rank', 'Hostile Status', 'Discord', 'Known Associates', 'Notes']:
            value = player.get(key, 'N/A')
            if key == 'Notes' and not value.strip():
                continue
            tk.Label(info_window, text=f"{key}:", bg='black', fg='white').grid(row=row, column=0, sticky='e')
            tk.Label(info_window, text=value, bg='black', fg='white').grid(row=row, column=1, sticky='w')
            row += 1

if __name__ == "__main__":
    root = tk.Tk()
    app = PlayerManagementApp(root)
    root.mainloop()
