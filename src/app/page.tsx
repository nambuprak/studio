
"use client";

import Link from 'next/link';
import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { BookOpen, Edit3, PlusSquare } from 'lucide-react';

// Mock data for repositories
const repositories = [
  { id: 'repo-alpha', name: 'Repo Alpha' },
  { id: 'repo-beta', name: 'Repo Beta' },
  { id: 'repo-gamma', name: 'Repo Gamma' },
  { id: 'repo-delta', name: 'Repo Delta' },
];

export default function HomePage() {
  const [selectedRepoId, setSelectedRepoId] = useState<string>('');
  const router = useRouter();

  const handleEditClick = () => {
    if (!selectedRepoId) {
      alert('Please select a repository from the dropdown to edit.');
      return;
    }
    router.push(`/edit?repoId=${selectedRepoId}`);
  };

  return (
    <main className="min-h-screen bg-background flex flex-col items-center justify-center p-4 sm:p-6 md:p-8">
      <Card className="w-full max-w-2xl shadow-2xl rounded-xl">
        <CardHeader className="text-center pt-8 pb-4">
          <CardTitle className="text-3xl sm:text-4xl font-bold text-primary">
            Self Tutor
            <span className="block sm:inline text-xl sm:text-2xl text-foreground/70 ml-0 sm:ml-2 mt-1 sm:mt-0">
              @My Company
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-8 p-6 md:p-8">
          <div className="space-y-2">
            <label htmlFor="repo-select-home" className="block text-sm font-medium text-foreground">
              Select Repository
            </label>
            <Select value={selectedRepoId} onValueChange={setSelectedRepoId}>
              <SelectTrigger id="repo-select-home" className="w-full text-base py-2.5">
                <SelectValue placeholder="Choose a repository..." />
              </SelectTrigger>
              <SelectContent>
                {repositories.map((repo) => (
                  <SelectItem key={repo.id} value={repo.id} className="text-base">
                    {repo.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Link href="/create" passHref legacyBehavior>
              <Button variant="default" size="lg" className="w-full text-base transition-all duration-200 ease-in-out hover:shadow-lg hover:scale-105 active:scale-95">
                <PlusSquare className="mr-2 h-5 w-5" /> Create
              </Button>
            </Link>
            <Link href="/learn" passHref legacyBehavior>
              <Button variant="default" size="lg" className="w-full text-base transition-all duration-200 ease-in-out hover:shadow-lg hover:scale-105 active:scale-95">
                <BookOpen className="mr-2 h-5 w-5" /> Learn
              </Button>
            </Link>
            <Button 
              variant="default" 
              size="lg" 
              className="w-full text-base transition-all duration-200 ease-in-out hover:shadow-lg hover:scale-105 active:scale-95"
              onClick={handleEditClick}
            >
              <Edit3 className="mr-2 h-5 w-5" /> Edit
            </Button>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
