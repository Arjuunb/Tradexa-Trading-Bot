import { Navbar } from "@/components/landing/Navbar";
import { Hero } from "@/components/landing/Hero";
import { EngineStatusBar } from "@/components/landing/EngineStatusBar";
import { Features } from "@/components/landing/Features";
import { BotThinking } from "@/components/landing/BotThinking";
import { EnginePipeline } from "@/components/landing/EnginePipeline";
import { ExecutionFlow } from "@/components/landing/ExecutionFlow";
import { TradeInAction } from "@/components/landing/TradeInAction";
import { MarketScanner } from "@/components/landing/MarketScanner";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { Connectivity } from "@/components/landing/Connectivity";
import { Screenshots } from "@/components/landing/Screenshots";
import { Performance } from "@/components/landing/Performance";
import { RiskGuard } from "@/components/landing/RiskGuard";
import { Security } from "@/components/landing/Security";
import { FinalCta } from "@/components/landing/FinalCta";
import { Footer } from "@/components/landing/Footer";

export default function Landing() {
  return (
    <>
      <Navbar />
      <Hero />
      <div className="mt-16 sm:mt-24">
        <EngineStatusBar />
      </div>
      <Features />
      <BotThinking />
      <EnginePipeline />
      <ExecutionFlow />
      <TradeInAction />
      <MarketScanner />
      <HowItWorks />
      <Connectivity />
      <Screenshots />
      <Performance />
      <RiskGuard />
      <Security />
      <FinalCta />
      <Footer />
    </>
  );
}
