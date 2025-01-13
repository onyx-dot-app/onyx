//import { Logo } from "../logo/Logo";
import { Logo } from "../EEA_Logo";

export default function AuthFlowContainer({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-background">
      <div className="w-full max-w-md bg-black pt-8 pb-4 px-8 mx-4 gap-y-4 bg-white flex items-center flex-col rounded-xl shadow-lg border border-bacgkround-100">
        <Logo width={92} height={70} />
        {children}
      </div>
    </div>
  );
}
