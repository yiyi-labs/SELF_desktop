// Process-local command interpreter adapter: preserves cwd despite a user's CMD AutoRun.
// CMake uses COMSPEC when generating Ninja shell rules. No registry changes are made.
using System;
using System.Diagnostics;
class BuildCmd {
 static int Main() {
  string command=Environment.CommandLine;
  int end=command.StartsWith("\"")?command.IndexOf('"',1)+1:command.IndexOf(' ');
  string rest=end<0?"":command.Substring(end).TrimStart();
  var start=new ProcessStartInfo(System.IO.Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"cmd.exe"),"/D "+rest);
  start.UseShellExecute=false;start.CreateNoWindow=true;start.WindowStyle=ProcessWindowStyle.Hidden;
  using(var process=Process.Start(start)){process.WaitForExit();return process.ExitCode;}
 }
}
