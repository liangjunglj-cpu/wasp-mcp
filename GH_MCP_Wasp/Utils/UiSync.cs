using System;
using System.Threading.Tasks;
using Rhino;

namespace GH_MCP_Wasp.Utils
{
    /// <summary>
    /// Marshals work from the TCP worker threads onto the Rhino UI thread.
    /// The TCP thread NEVER touches GH_Document directly; every canvas
    /// read/mutation goes through OnUi, which blocks the calling worker thread
    /// (never the UI thread) until the UI action completes or 30 s elapse.
    /// </summary>
    public static class UiSync
    {
        public const int DefaultTimeoutMs = 30000;

        /// <summary>
        /// Run a function on the Rhino UI thread and marshal the result (or
        /// exception) back to the calling thread via a TaskCompletionSource.
        /// Throws TimeoutException after 30 s so the bridge never hangs.
        /// </summary>
        public static T OnUi<T>(Func<T> func, int timeoutMs = DefaultTimeoutMs)
        {
            var tcs = new TaskCompletionSource<T>(TaskCreationOptions.RunContinuationsAsynchronously);

            RhinoApp.InvokeOnUiThread(new Action(() =>
            {
                try
                {
                    tcs.TrySetResult(func());
                }
                catch (Exception ex)
                {
                    tcs.TrySetException(ex);
                }
            }));

            bool completed;
            try
            {
                completed = tcs.Task.Wait(timeoutMs);
            }
            catch (AggregateException ae)
            {
                throw ae.InnerException ?? ae;
            }

            if (!completed)
            {
                throw new TimeoutException($"UI thread operation timed out after {timeoutMs / 1000} s");
            }

            return tcs.Task.Result;
        }
    }
}
