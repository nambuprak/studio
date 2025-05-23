
"use client";

import Link from 'next/link';
import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { BookOpen, Edit3, PlusSquare } from 'lucide-react';

interface Repository {
  id: string;
  name: string;
}

export default function HomePage() {
  const [selectedRepoId, setSelectedRepoId] = useState<string>('');
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const router = useRouter();

  useEffect(() => {
    async function fetchRepositories() {
      try {
        // Ensure your Flask server is running on port 5001 (or the port you configured)
        const response = await fetch('http://localhost:5001/api/repos');
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const data: Repository[] = await response.json();
        setRepositories(data);
      } catch (error) {
        console.error("Failed to fetch repositories:", error);
        setRepositories([]);
        let errorMessage = "Could not fetch repositories. Make sure the Flask API server is running on port 5001.";
        if (error instanceof Error) {
          errorMessage += `\nDetails: ${error.message}`;
        }
        alert(errorMessage);
      }
    }
    fetchRepositories();
  }, []);

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
                {repositories.length > 0 ? (
                  repositories.map((repo) => (
                    <SelectItem key={repo.id} value={repo.id} className="text-base">
                      {repo.name}
                    </SelectItem>
                  ))
                ) : (
                  <SelectItem value="loading" disabled className="text-base">
                    {repositories.length === 0 && !selectedRepoId ? "Failed to load. Is the API server running?" : "Loading repositories..."}
                  </SelectItem>
                )}
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
              disabled={repositories.length === 0 && !selectedRepoId}
            >
              <Edit3 className="mr-2 h-5 w-5" /> Edit
            </Button>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
