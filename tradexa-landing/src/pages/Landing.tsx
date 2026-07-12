import { Navbar } from "@/components/landing/Navbar";
import { Hero } from "@/components/landing/Hero";
import { EngineStatusBar } from "@/components/landing/EngineStatusBar";
import { Features } from "@/components/landing/Features";
import { EnginePipeline } from "@/components/landing/EnginePipeline";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { Screenshots } from "@/components/landing/Screenshots";
import { Performance } from "@/components/landing/Performance";
import { Security } from "@/components/landing/Security";
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
      <EnginePipeline />
      <HowItWorks />
      <Screenshots />
      <Performance />
      <Security />
      <Footer />
    </>
  );
}
