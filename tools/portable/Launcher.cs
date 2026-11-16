// HandPilot.exe: starts the bundled Python (runtime\pythonw.exe) with app\HandPilot.pyw. No console window.
using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

static class Launcher
{
    [STAThread]
    static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(root, "runtime", "pythonw.exe");
        string script = Path.Combine(root, "app", "HandPilot.pyw");
        if (!File.Exists(python) || !File.Exists(script))
        {
            MessageBox.Show("Не найдены файлы приложения (папки runtime и app).\n" +
                            "Распакуйте архив целиком и запускайте HandPilot.exe из распакованной папки, " +
                            "не из окна архива.", "HandPilot", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        var cmd = new StringBuilder("\"" + script + "\"");
        foreach (string a in args) cmd.Append(" \"").Append(a.Replace("\"", "\\\"")).Append('"');
        var psi = new ProcessStartInfo(python, cmd.ToString())
        {
            WorkingDirectory = Path.Combine(root, "app"),
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        psi.EnvironmentVariables["PYTHONNOUSERSITE"] = "1";   // never pick up packages from the user's own Python
        psi.EnvironmentVariables["PYTHONHOME"] = "";
        try { Process.Start(psi); }
        catch (Exception e)
        {
            MessageBox.Show("Не удалось запустить HandPilot:\n" + e.Message, "HandPilot",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        return 0;
    }
}
