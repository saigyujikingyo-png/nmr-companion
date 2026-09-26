// NMR Companion native Windows entrypoint. Distributed under the project MIT license.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

public static class NativeLauncher
{
    // ProcessStartInfo on .NET Framework needs a Windows command line, not shell code.
    public static string QuoteArgument(string value)
    {
        StringBuilder result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char item in value)
        {
            if (item == '\\') { slashes++; continue; }
            if (item == '"')
            {
                result.Append('\\', slashes * 2 + 1);
                result.Append('"');
            }
            else
            {
                result.Append('\\', slashes);
                result.Append(item);
            }
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }

    public static ProcessStartInfo StartInfo(string root, string[] arguments)
    {
        List<string> values = new List<string>(new string[] {
            "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            Path.Combine(root, "Launch.ps1"), "-Mode", "desktop"
        });
        if (arguments.Length != 0)
        {
            if (arguments.Length != 2 || arguments[0] != "--project" ||
                String.IsNullOrWhiteSpace(arguments[1]))
                throw new ArgumentException("Use NMR Companion.exe with no arguments, or --project followed by a project path.");
            values.Add("-Project");
            values.Add(Path.GetFullPath(arguments[1]));
        }
        ProcessStartInfo info = new ProcessStartInfo();
        info.FileName = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),
            @"WindowsPowerShell\v1.0\powershell.exe");
        info.Arguments = String.Join(" ", values.ConvertAll(QuoteArgument).ToArray());
        info.WorkingDirectory = root;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.WindowStyle = ProcessWindowStyle.Hidden;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        return info;
    }

    private static Dictionary<string, object> ReadJson(string path)
    {
        return new JavaScriptSerializer { MaxJsonLength = 32 * 1024 * 1024 }
            .Deserialize<Dictionary<string, object>>(File.ReadAllText(path, Encoding.UTF8));
    }

    private static string Hash(string path)
    {
        using (FileStream input = File.OpenRead(path))
        using (SHA256 algorithm = SHA256.Create())
            return BitConverter.ToString(algorithm.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
    }

    private static void AssertNativeRelease(string root)
    {
        Dictionary<string, object> state = ReadJson(Path.Combine(root, "installation.json"));
        string active = Convert.ToString(state["active"]);
        if (Convert.ToString(state["product"]) != "nmr-companion" ||
            !System.Text.RegularExpressions.Regex.IsMatch(active, @"\A[A-Za-z0-9][A-Za-z0-9.+-]*-[a-f0-9]{12}\z"))
            throw new InvalidDataException("The installation pointer is invalid. Run Verify.cmd.");
        string manifestPath = Path.Combine(root, "releases", active, "manifest.json");
        string expected = null;
        foreach (object item in (System.Collections.IEnumerable)state["releases"])
        {
            Dictionary<string, object> release = (Dictionary<string, object>)item;
            if (Convert.ToString(release["id"]) == active)
                expected = Convert.ToString(release["manifest_sha256"]);
        }
        if (expected == null || Hash(manifestPath) != expected)
            throw new InvalidDataException("The runtime manifest changed. Run Verify.cmd.");
        Dictionary<string, object> manifest = ReadJson(manifestPath);
        object frontend;
        if (!manifest.TryGetValue("desktop_frontend", out frontend) ||
            Convert.ToString(frontend) != "qt-widgets")
            throw new InvalidOperationException("This restored release does not include the native Windows workbench. Upgrade to a native release to open the desktop application. Your project files remain available.");
    }

    private static void AppendTail(StringBuilder text, string line)
    {
        if (line == null) return;
        lock (text)
        {
            text.AppendLine(line);
            if (text.Length > 8000) text.Remove(0, text.Length - 8000);
        }
    }

    // The error reporter is injectable for tests; the shipped entrypoint uses a native dialog.
    public static int Run(string root, string[] arguments, Action<string> reportError)
    {
        try
        {
            ProcessStartInfo info = StartInfo(root, arguments);
            using (FileStream installationLock = new FileStream(Path.Combine(root, ".installation.lock"),
                FileMode.Open, FileAccess.Read, FileShare.Read))
            {
                if (File.Exists(Path.Combine(root, "pending.json")))
                    throw new InvalidOperationException("Installation was interrupted. Run Recover.cmd before opening the application.");
                AssertNativeRelease(root);
                using (Process process = new Process())
                {
                    StringBuilder output = new StringBuilder();
                    process.StartInfo = info;
                    process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { AppendTail(output, e.Data); };
                    process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { AppendTail(output, e.Data); };
                    if (!process.Start()) throw new InvalidOperationException("Windows could not start the application.");
                    process.BeginOutputReadLine();
                    process.BeginErrorReadLine();
                    process.WaitForExit();
                    if (process.ExitCode != 0)
                        throw new InvalidOperationException("The workbench exited with code " + process.ExitCode + ".\n\n" + output.ToString().Trim());
                    return 0;
                }
            }
        }
        catch (Exception error)
        {
            reportError("NMR Companion could not open.\n\n" + error.Message);
            return 1;
        }
    }

    [STAThread]
    public static int Main(string[] arguments)
    {
        string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        return Run(root, arguments, delegate(string message) {
            MessageBox.Show(message, "NMR Companion", MessageBoxButtons.OK, MessageBoxIcon.Error);
        });
    }
}
