**Getting AI tools running on Windows**

Follow these steps in order. Before you begin, open **PowerShell as Administrator**: press **Win + S**, type PowerShell, right-click it, and select *Run as administrator*.

**Step 1 --- Install Claude Code**

Claude Code requires Node.js. Install it first using winget, then install Claude:

*Paste this into PowerShell to install Node.js:*

> winget install OpenJS.NodeJS.LTS

*Close and reopen PowerShell, then install Claude Code:*

> npm install -g @anthropic-ai/claude-code

*Confirm it worked:*

> claude --version

*Note: If you see a version number printed, Claude is installed correctly.*

**Step 2 --- Install Git**

*Run this in PowerShell:*

> winget install --id Git.Git -e

*Close and reopen PowerShell, then confirm:*

> git --version

*Note: Git for Windows also installs Git Bash, which lets you run bash-style commands if needed.*

**Step 3 --- Add Stata to your PATH**

This lets Claude find and run Stata directly from the terminal. Follow these sub-steps carefully.

**3a. Find your Stata installation**

Stata is typically installed in one of these locations:

> C:\Program Files\Stata18\StataMP-64.exe
>
> C:\Program Files\Stata17\StataMP-64.exe

*Run this to search for it:*

> Get-ChildItem "C:\Program Files" -Recurse -Filter "Stata*.exe" -ErrorAction SilentlyContinue | Select-Object FullName

*Note: If you have multiple versions, use the path for the newest one.*

**3b. Add Stata to your PATH**

*Run this in PowerShell (replace the path with your actual Stata folder if different):*

> [System.Environment]::SetEnvironmentVariable("Path", $env:Path + ";C:\Program Files\Stata18", [System.EnvironmentVariableTarget]::User)

*Close and reopen PowerShell, then test that Stata runs:*

> StataMP-64 /e do NUL

*Note: If Stata opens briefly and closes without an error, it is correctly connected to your terminal.*

**Step 4 --- Create the Stata skill file for Claude**

This creates a CLAUDE.md file in your project folder that tells Claude how to run your Stata code. Do this once per project.

*Navigate to your project folder (replace the path with your own):*

> cd "C:\Users\yourname\Dropbox\Research\YourProject"

*Then create the CLAUDE.md file:*

> @"
> ## Stata
> - Run do-files with: StataMP-64 /e do filename.do
> - Output logs appear as filename.log in the same directory
> - Always check the .log file after running to see results and errors
> - Stata version: 18 (StataMP)
> - Executable: C:\Program Files\Stata18\StataMP-64.exe
> "@ | Out-File -FilePath CLAUDE.md -Encoding utf8

*Confirm it was created:*

> Get-Content CLAUDE.md

*Note: You should see the Stata instructions printed back. This file tells Claude how to run and debug your code automatically.*

**Step 5 --- Install supporting tools**

*pandoc --- convert between document formats (you may already have this):*

> winget install --id JohnMacFarlane.Pandoc -e

*pdfplumber --- extract text and tables from PDFs (requires Python):*

> pip install pdfplumber

*Note: If pip is not found, install Python first: `winget install Python.Python.3`*

**Step 6 --- Set up Git for version control**

Git lets you save snapshots of your project so you can undo changes if something goes wrong --- especially useful when Claude Code is editing your files.

**6a. One-time setup per project**

*Navigate to your project folder and initialize Git:*

> cd "C:\Users\yourname\Dropbox\Research\YourProject"
>
> git init
>
> git add .
>
> git commit -m "Initial save"

*Note: You only need to do this once per project. It creates a hidden .git folder that tracks all future changes.*

**6b. Save a snapshot before Claude makes big changes**

*Run these two commands before asking Claude to do anything large:*

> git add .
>
> git commit -m "Before Claude rewrites analysis.do"

*Note: Write a short description of the current state in the commit message so you can find it later.*

**6c. Undo changes if something goes wrong**

*To revert all files back to your last saved snapshot:*

> git restore .

*Note: This undoes all changes since your last commit. Your last saved snapshot is fully restored.*

**6d. View your save history**

*To see a list of all your past snapshots:*

> git log --oneline

**Step 7 --- Connect to GitHub for collaboration**

GitHub is a website where you store your Git history online so coauthors can access it. You can make repositories private so only invited collaborators can see them. Git (local) and GitHub (online) work together --- everything from Step 6 carries over.

**7a. Create a GitHub account and a private repository**

Go to **github.com** and create a free account. Then click *New repository*, give it a name, and set it to **Private**. Do not initialize it with any files --- leave it empty.

**7b. One-time setup: tell Git who you are**

*Run these once on your machine (use the email you signed up to GitHub with):*

> git config --global user.name "Your Name"
>
> git config --global user.email "you@email.com"

**7c. Connect your local project to GitHub**

*Navigate to your project folder and run these commands (replace the URL with your own repository URL from GitHub):*

> cd "C:\Users\yourname\Dropbox\Research\YourProject"
>
> git remote add origin https://github.com/yourusername/yourrepo.git
>
> git push -u origin main

*Note: GitHub will ask for your username and password the first time. After that it remembers. If it asks for a token instead of a password, generate one at github.com → Settings → Developer settings → Personal access tokens.*

**7d. Invite your coauthors**

On GitHub, go to your repository → *Settings → Collaborators* → *Add people*. Enter their GitHub username or email. They will receive an invitation to access the private repository.

**7e. Ongoing workflow with coauthors**

*After committing your changes (Step 6b), upload them to GitHub:*

> git push

*To download your coauthors' latest changes:*

> git pull

*Note: Always run 'git pull' before starting work to make sure you have the latest version from your coauthors.*

**All done!**

You're fully set up. Open a new PowerShell window, navigate to your project folder, type `claude` and press Enter, and ask Claude to run your Stata files directly.
