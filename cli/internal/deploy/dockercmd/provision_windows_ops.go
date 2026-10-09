package dockercmd

// Windows provisioning is detect-and-instruct: when Docker Desktop (with the
// WSL2 backend) is present, every deploy verb works like on other platforms;
// when it's missing, the install prints these instructions and exits instead
// of self-elevating or installing software unattended.

// DockerDesktopInstructionsWindows is printed when no working Docker is found
// on native Windows.
const DockerDesktopInstructionsWindows = `Docker Desktop was not found. To run Onyx on Windows:

  1. Install WSL2 (in an elevated PowerShell):  wsl --install
  2. Install Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/
  3. Start Docker Desktop and enable the WSL2 backend (Settings > General)
  4. Re-run this command

Alternatively, run the installer inside a WSL2 distribution, where Docker
Engine can be installed automatically.`
