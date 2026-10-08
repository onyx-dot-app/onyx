// NOTE(@raunakab): This behaviour is up for debate. Therefore, keeping it as a
// var that we can easily flip in the future. An indeterminate check finished
// without an answer (a timeout, a 5xx, an unknown error), which is not proof
// that the credential is broken; re-running it often settles it. While this is
// false, a required indeterminate check blocks neither the form nor Create.
export const INDETERMINATE_CHECKS_BLOCK: boolean = false;
