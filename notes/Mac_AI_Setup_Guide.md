**Getting AI tools running on your Mac**

Follow these steps in order. Before you begin, open Terminal on your Mac: press **⌘ + Space**, type Terminal, and press Enter.

**Step 1 --- Install Claude Code**

*Paste this into Terminal to install Claude:*

> curl -fsSL https://claude.ai/install.sh \| bash

*Terminal will ask you to run these two commands to finish setup:*

> echo \'export PATH=\"\$HOME/.local/bin:\$PATH\"\' \>\> \~/.zshrc && source \~/.zshrc
>
> claude \--version

*Note: If you see a version number printed, Claude is installed correctly.*

**Step 2 --- Install Git**

*Run this --- it will prompt you to install Apple\'s developer tools, including Git:*

> xcode-select \--install

*Confirm it worked:*

> git \--version

*Note: A window may pop up asking you to install developer tools --- click Install and wait for it to finish.*

**Step 3 --- Install Homebrew**

Homebrew is a package manager that makes it easy to install software on a Mac.

*Run:*

> /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/homebrew/install/HEAD/install.sh)\"

*Note: This may take a few minutes and will ask for your Mac password. That is normal.*

**Step 4 --- Add Stata to your PATH**

This lets Claude find and run Stata directly from the terminal. Follow these sub-steps carefully.

**4a. Find your Stata installation**

*Run this to locate Stata on your Mac:*

> find /Applications -maxdepth 3 -name \"\*.app\" \| grep -i stata

You will see one or more lines like:

> /Applications/Stata/StataMP.app
>
> /Applications/Stata 15.0/StataMP.app

*Note: If you have multiple versions, use the path for the newest one (e.g. the one without a version number in the folder name is typically the latest).*

**4b. Add Stata to your PATH**

*Run this command to add Stata to your PATH:*

> echo \'export PATH=\"/Applications/Stata/StataMP.app/Contents/MacOS:\$PATH\"\' \>\> \~/.zshrc

*Note: If your Stata app is at a different path from step 4a, replace /Applications/Stata/StataMP.app with your actual path.*

**4c. Reload your shell and test**

*Reload your settings:*

> source \~/.zshrc

*Test that Stata runs:*

> stata-mp -q -b -e \"display 1\" && cat stata.log

*Note: You should see a 1 printed. If so, Stata is correctly connected to your terminal.*

**Step 5 --- Create the Stata skill file for Claude**

This creates a CLAUDE.md file in your project folder that tells Claude how to run your Stata code. Do this once per project.

*Navigate to your project folder (replace the path with your own):*

> cd \"/Users/yourname/Dropbox/Research/YourProject\"

*Then create the CLAUDE.md file:*

> cat \> CLAUDE.md \<\< \'EOF\' \## Stata - Run do-files with: stata-mp -q -b do filename.do - Output logs appear as filename.log in the same directory - Always check the .log file after running to see results and errors - Stata version: 18 (StataMP) - Executable: /Applications/Stata/StataMP.app/Contents/MacOS/stata-mp EOF

*Confirm it was created:*

> cat CLAUDE.md

*Note: You should see the Stata instructions printed back. This file tells Claude how to run and debug your code automatically.*

**Step 6 --- Install supporting tools**

Run each of the following commands one at a time:

*pdfgrep --- search through PDFs:*

> brew install pdfgrep

*pandoc --- convert between document formats:*

> brew install pandoc

*pdfplumber --- extract text and tables from PDFs:*

> pip install pdfplumber

**Step 7 --- Set up Git for version control**

Git lets you save snapshots of your project so you can undo changes if something goes wrong --- especially useful when Claude Code is editing your files.

**7a. One-time setup per project**

*Navigate to your project folder and initialize Git:*

> cd \"/Users/yourname/Dropbox/Research/YourProject\"
>
> git init
>
> git add .
>
> git commit -m \"Initial save\"

*Note: You only need to do this once per project. It creates a hidden Git folder that tracks all future changes.*

**7b. Save a snapshot before Claude makes big changes**

*Run these two commands before asking Claude to do anything large:*

> git add .
>
> git commit -m \"Before Claude rewrites analysis.do\"

*Note: Write a short description of the current state in the commit message so you can find it later.*

**7c. Undo changes if something goes wrong**

*To revert all files back to your last saved snapshot:*

> git restore .

*Note: This undoes all changes since your last commit. Your last saved snapshot is fully restored.*

**7d. View your save history**

*To see a list of all your past snapshots:*

> git log \--oneline

**Step 8 --- Connect to GitHub for collaboration**

GitHub is a website where you store your Git history online so coauthors can access it. You can make repositories private so only invited collaborators can see them. Git (local) and GitHub (online) work together --- everything from Step 7 carries over.

**8a. Create a GitHub account and a private repository**

Go to **github.com** and create a free account. Then click *New repository*, give it a name, and set it to **Private**. Do not initialize it with any files --- leave it empty.

**8b. One-time setup: tell Git who you are**

*Run these once on your Mac (use the email you signed up to GitHub with):*

> git config \--global user.name \"Your Name\"
>
> git config \--global user.email \"you@email.com\"

**8c. Connect your local project to GitHub**

*Navigate to your project folder and run these commands (replace the URL with your own repository URL from GitHub):*

> cd \"/Users/yourname/Dropbox/Research/YourProject\"
>
> git remote add origin https://github.com/yourusername/yourrepo.git
>
> git push -u origin main

*Note: GitHub will ask for your username and password the first time. After that it remembers.*

**8d. Invite your coauthors**

On GitHub, go to your repository → *Settings → Collaborators* → *Add people*. Enter their GitHub username or email. They will receive an invitation to access the private repository.

**8e. Ongoing workflow with coauthors**

*After committing your changes (Step 7b), upload them to GitHub:*

> git push

*To download your coauthors\' latest changes:*

> git pull

*Note: Always run \'git pull\' before starting work to make sure you have the latest version from your coauthors.*

**All done!**

You\'re fully set up. Navigate to your project folder, type claude in Terminal, and ask Claude to run your Stata files directly.
