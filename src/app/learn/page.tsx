import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ArrowLeft, BookOpen } from 'lucide-react';

export default function LearnPage() {
  return (
    <main className="min-h-screen bg-background flex flex-col items-center justify-center p-4 sm:p-6 md:p-8">
      <Card className="w-full max-w-xl text-center shadow-xl rounded-lg">
        <CardHeader>
          <CardTitle className="text-3xl font-bold text-primary flex items-center justify-center">
            <BookOpen className="mr-3 h-8 w-8" /> Learn
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <p className="text-lg text-foreground">
            This is the placeholder for the Learn page. Interactive learning modules and content related to the selected repository will be available here.
          </p>
          <Link href="/" passHref legacyBehavior>
            <Button variant="outline" size="lg">
              <ArrowLeft className="mr-2 h-5 w-5" /> Go Back to Home
            </Button>
          </Link>
        </CardContent>
      </Card>
    </main>
  );
}
