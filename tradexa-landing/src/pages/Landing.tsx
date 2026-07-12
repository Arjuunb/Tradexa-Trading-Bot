import { Navbar } from "@/components/landing/Navbar";
import { Hero } from "@/components/landing/Hero";
import { Features } from "@/components/landing/Features";
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
      <Features />
      <HowItWorks />
      <Screenshots />
      <Performance />
      <Security />
      <Footer />
    </>
  );
}
